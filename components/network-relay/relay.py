#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenJustSayAI
"""Loopback-only, opaque TCP relay to health-checked HTTP proxies. Stdlib only."""
import argparse
import asyncio
import contextlib
import copy
import ipaddress
import inspect
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import tempfile
import time

DEFAULT = {
    'listen_port': 18080, 'connect_timeout': 4, 'health_timeout': 8, 'health_interval': 20,
    'mac': {'host': 'localhost', 'port': 1082, 'enabled': False},
    'profiles': {},
}
RFC1918 = tuple(ipaddress.IPv4Network(block) for block in
                ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def private_subnet(value):
    """Require an explicit RFC1918 IPv4 /24 or smaller; never scan broad/public ranges."""
    if not isinstance(value, str):
        raise ValueError('CIDR string required')
    subnet = ipaddress.IPv4Network(value)
    if subnet.prefixlen < 24 or not any(subnet.subnet_of(block) for block in RFC1918):
        raise ValueError('only RFC1918 IPv4 /24 or smaller subnets are allowed')
    return subnet


def usable_address(value, subnet):
    if not isinstance(value, str):
        raise ValueError('IPv4 address string required')
    address = ipaddress.IPv4Address(value)
    return address in subnet and address not in (subnet.network_address, subnet.broadcast_address)


def validate_config(raw):
    """Normalize explicitly configured profiles and bind each to its actual Wi-Fi SSID."""
    if not isinstance(raw, dict) or set(raw) - (set(DEFAULT) | {'listen_host'}):
        raise ValueError('unsupported config keys')
    if raw.get('listen_host', '127.0.0.1') != '127.0.0.1':
        raise ValueError('listen_host must be 127.0.0.1')
    result = copy.deepcopy(DEFAULT)
    for key, value in raw.items():
        if key in ('mac', 'profiles'):
            if not isinstance(value, dict): raise ValueError('object required')
            if key == 'mac': result[key].update(value)
            else: result[key] = copy.deepcopy(value)
        else: result[key] = value
    for key in ('listen_port', 'connect_timeout', 'health_timeout', 'health_interval'):
        value = result[key]
        maximum = 65535 if key == 'listen_port' else 120
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= maximum:
            raise ValueError('invalid ' + key)
    if not isinstance(result['listen_port'], int): raise ValueError('integer listen_port required')
    mac = result['mac']
    if set(mac) - {'host', 'port', 'enabled'} or type(mac['enabled']) is not bool:
        raise ValueError('invalid mac proxy')
    if not isinstance(mac['host'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', mac['host']):
        raise ValueError('proxy host must contain no URL or credentials')
    if type(mac['port']) is not int or not 1 <= mac['port'] <= 65535:
        raise ValueError('invalid proxy port')
    for name, endpoint in result['profiles'].items():
        if not isinstance(name, str) or not name or any(char in name for char in '\x00\r\n'):
            raise ValueError('nonempty Wi-Fi SSID required')
        if not isinstance(endpoint, dict): raise ValueError('profile object required')
        gateway = endpoint.get('gateway') is True
        fields = {'gateway', 'port'} if gateway else {'ip', 'mac', 'port', 'allowed_cidrs'}
        if set(endpoint) != fields: raise ValueError('incomplete or unsupported network profile')
        if type(endpoint['port']) is not int or not 1 <= endpoint['port'] <= 65535:
            raise ValueError('invalid proxy port')
        if not gateway:
            cidrs = endpoint['allowed_cidrs']
            if not isinstance(cidrs, list) or not cidrs: raise ValueError('nonempty allowed_cidrs required')
            subnets = [private_subnet(block) for block in cidrs]
            if not any(usable_address(endpoint['ip'], subnet) for subnet in subnets):
                raise ValueError('phone IP must be a usable address in an approved subnet')
            if not isinstance(endpoint['mac'], str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', endpoint['mac']):
                raise ValueError('invalid phone MAC')
        endpoint['_ssid'] = name  # Internal only: callers cannot provide/override this field.
    return result


def command_json(args):
    return json.loads(subprocess.check_output(args, timeout=2, stderr=subprocess.DEVNULL))


def read_network():
    """Read actual Wi-Fi SSID by active UUID, independently of its profile name."""
    try:
        routes = command_json(['ip', '-j', '-4', 'route', 'show', 'default'])
        route = min((r for r in routes if r.get('dev')), key=lambda r: r.get('metric', 0))
        interface = route['dev']
        info = command_json(['ip', '-j', '-4', 'addr', 'show', 'dev', interface])[0]
        addr = next(a for a in info['addr_info'] if a.get('scope') == 'global')
        fields = subprocess.check_output(['nmcli', '-g', 'GENERAL.TYPE,GENERAL.CON-UUID', 'device', 'show', interface], timeout=2, stderr=subprocess.DEVNULL).decode().splitlines()
        if len(fields) != 2 or fields[0] != 'wifi' or not fields[1]: return dict(name='unknown')
        name = subprocess.check_output(['nmcli', '--escape', 'no', '-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', fields[1]], timeout=2, stderr=subprocess.DEVNULL).decode().rstrip('\n')
        link = command_json(['ip', '-j', 'link', 'show', 'dev', interface])[0]
        return dict(name=name, interface=interface, local=addr['local'], prefix=addr['prefixlen'], gateway=route.get('gateway'), mac=link['address'])
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError):
        return dict(name='unknown')


def parse_arp(packet, expected_mac, local_ip, prefix, local_mac):
    """Validate Ethernet/ARP reply identity, target and local subnet before using its IP."""
    try:
        wanted = bytes.fromhex(expected_mac.replace(':', ''))
        local = bytes.fromhex(local_mac.replace(':', ''))
        if len(packet) < 42 or packet[:6] != local or packet[6:12] != wanted or packet[12:14] != b'\x08\x06': return None
        if struct.unpack('!HHBBH', packet[14:22]) != (1, 0x800, 6, 4, 2): return None
        if packet[22:28] != wanted or packet[32:38] != local or packet[38:42] != socket.inet_aton(local_ip): return None
        source = ipaddress.IPv4Address(packet[28:32])
        network = ipaddress.IPv4Network(prefix, strict=False)
        if source not in network or source in (network.network_address, network.broadcast_address, ipaddress.IPv4Address(local_ip)): return None
        return str(source)
    except (ValueError, OSError, struct.error):
        return None


def discover_phone(profile, network):
    """Only trust MAC-matched neighbor/ARP data; stale configured IP alone is insufficient."""
    if not isinstance(profile, dict) or not profile.get('_ssid') or network.get('name') != profile['_ssid']:
        return None
    try:
        subnet = private_subnet(str(ipaddress.IPv4Network(f"{network['local']}/{network['prefix']}", strict=False)))
        if not usable_address(network['local'], subnet): return None
        if profile.get('gateway'):
            gateway = network.get('gateway')
            return gateway if gateway != network['local'] and usable_address(gateway, subnet) else None
        if not any(subnet.subnet_of(private_subnet(block)) for block in profile.get('allowed_cidrs', [])):
            return None
        interface, mac = network['interface'], profile['mac'].lower()
        neighbors = command_json(['ip', '-j', '-4', 'neigh', 'show', 'dev', interface])
        matches = [n['dst'] for n in neighbors if n.get('lladdr', '').lower() == mac and n.get('state') and not set(n['state']) & {'FAILED', 'INCOMPLETE'} and usable_address(n['dst'], subnet) and n['dst'] != network['local']]
        if profile['ip'] in matches: return profile['ip']
        if matches: return matches[0]
        if not hasattr(socket, 'AF_PACKET'): return None
        own = bytes.fromhex(network['mac'].replace(':', ''))
        sender = socket.inet_aton(network['local'])
        header = b'\xff' * 6 + own + b'\x08\x06' + struct.pack('!HHBBH', 1, 0x800, 6, 4, 1) + own + sender + b'\x00' * 6
        # No external scan: trusted profile, active RFC1918 /24 or smaller, <=254 hosts.
        with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806)) as sock:
            sock.bind((interface, 0)); sock.settimeout(0.02)
            hosts = list(subnet.hosts())
            preferred = ipaddress.IPv4Address(profile['ip'])
            if preferred in hosts: hosts.remove(preferred); hosts.insert(0, preferred)
            start = time.monotonic()
            transmit_deadline, deadline = start + 2.5, start + 3.5
            def receive_ready():
                sock.settimeout(0)
                for _ in range(64):
                    try: packet, address = sock.recvfrom(2048)
                    except (BlockingIOError, socket.timeout): return None
                    if address[0] == interface:
                        found = parse_arp(packet, mac, network['local'], str(subnet), network['mac'])
                        if found: return found
                return None
            index = 0
            while index < len(hosts) and time.monotonic() < transmit_deadline:
                batch_start = time.monotonic()
                sock.settimeout(0)  # Do not let Wi-Fi TX backpressure starve reception.
                for _ in range(8):
                    if index >= len(hosts) or time.monotonic() >= transmit_deadline: break
                    host = hosts[index]
                    if str(host) != network['local']:
                        try: sock.send(header + host.packed)
                        except (BlockingIOError, socket.timeout): break  # Retry same target next batch.
                    index += 1
                found = receive_ready()  # Drain even when the transmit budget just expired.
                if found: return found
                delay = min(.0625 - (time.monotonic()-batch_start), transmit_deadline-time.monotonic())
                if delay > 0: time.sleep(delay)  # At most eight packets per 62.5ms batch.
            while time.monotonic() < deadline:
                sock.settimeout(max(0.001, deadline-time.monotonic()))
                packet, address = sock.recvfrom(2048)
                if address[0] != interface: continue
                found = parse_arp(packet, mac, network['local'], str(subnet), network['mac'])
                if found: return found
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass  # CAP_NET_RAW unavailable or network changed; never guess an old DHCP address.
    return None


async def check_proxy(endpoint, timeout):
    """Explicit CONNECT then system-verified TLS; no environment proxy or direct fallback."""
    async def probe():
        writer = None
        try:
            reader, writer = await asyncio.open_connection(endpoint['host'], endpoint['port'])
            writer.write(b'CONNECT huggingface.co:443 HTTP/1.1\r\nHost: huggingface.co:443\r\n\r\n')
            await writer.drain()
            response = await reader.readuntil(b'\r\n\r\n')
            if response.split(b'\r\n', 1)[0].split()[1:2] != [b'200']: return False
            await writer.start_tls(ssl.create_default_context(), server_hostname='huggingface.co', ssl_handshake_timeout=timeout)
            writer.write(b'HEAD / HTTP/1.1\r\nHost: huggingface.co\r\nConnection: close\r\n\r\n')
            await writer.drain()
            status = (await reader.readline()).split()
            return len(status) >= 2 and status[0].startswith(b'HTTP/') and 200 <= int(status[1]) < 400
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return False
        finally:
            if writer:
                writer.close()
                with contextlib.suppress(OSError, asyncio.TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), 0.2)
    try:
        return await asyncio.wait_for(probe(), timeout)
    except asyncio.TimeoutError:
        return False


class Relay:
    def __init__(self, config_path, status_path, network_reader=read_network, health_checker=check_proxy, phone_discoverer=discover_phone):
        self.config_path, self.status_path = config_path, status_path
        self.network_reader, self.health_checker, self.phone_discoverer = network_reader, health_checker, phone_discoverer
        self.server = self.monitor = None
        self.healthy, self.selected, self.network = [], None, {'name': 'unknown'}
        self.config = validate_config({}); self.signature = None; self.checked = 0
        self.clients = set()
        self.generation = 0
        self.state_lock = asyncio.Lock()

    def write_status(self, error=None):
        status = dict(network=self.network, healthy=self.healthy, selected=self.selected, checked_at=self.checked, updated_at=time.time())
        if error: status['error'] = error
        directory = os.path.dirname(os.path.abspath(self.status_path))
        fd, temporary = tempfile.mkstemp(prefix='.relay-status-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(status, stream); stream.write('\n')
            os.replace(temporary, self.status_path)
        finally:
            with contextlib.suppress(FileNotFoundError): os.unlink(temporary)

    async def observe(self):
        # Serialize observations so an older delayed read cannot overwrite newer state.
        async with self.state_lock:
            try:
                network = await asyncio.to_thread(self.network_reader)
                with open(self.config_path) as stream: config = validate_config(json.load(stream))
                signature = json.dumps([config, network], sort_keys=True)
                error = None
            except (OSError, ValueError, TypeError, KeyError):
                config, network, signature = self.config, {'name': 'unknown'}, None
                error = 'configuration or network unavailable'
            if signature != self.signature:
                self.generation += 1
                self.checked = 0
                self.healthy, self.selected = [], None
                self.config, self.network, self.signature = config, network, signature
                for task in list(self.clients):
                    if task is not asyncio.current_task(): task.cancel()
                self.write_status(error)
            return self.generation

    async def refresh(self, force=True):
        before = self.generation
        generation = await self.observe()
        config, network = self.config, self.network
        if self.signature is None: return
        if not force and generation == before and time.time() - self.checked < config['health_interval']: return
        candidates = []
        if config['mac']['enabled']:
            candidates.append(dict(name='mac', host=config['mac']['host'], port=config['mac']['port']))
        profile = config['profiles'].get(network['name'])
        if profile:
            address = await asyncio.to_thread(self.phone_discoverer, profile, network)
            if generation != await self.observe(): return
            if address: candidates.append(dict(name='phone', host=address, port=profile['port']))
        async def healthy(endpoint):
            try:
                check = self.health_checker(endpoint, config['health_timeout']) if inspect.iscoroutinefunction(self.health_checker) else asyncio.to_thread(self.health_checker, endpoint, config['health_timeout'])
                ok = await asyncio.wait_for(check, config['health_timeout'])
                return endpoint if ok else None
            except Exception: return None
        checked = await asyncio.gather(*(healthy(e) for e in candidates))
        if generation != await self.observe(): return
        self.healthy = [item for item in checked if item]
        self.checked = time.time()
        self.write_status()

    async def handle(self, reader, writer):
        task = asyncio.current_task(); self.clients.add(task)
        upstream = None
        try:
            generation = await self.observe()
            config, network = self.config, self.network
            for endpoint in list(self.healthy):
                if generation != self.generation: return
                try:
                    if endpoint['name'] == 'phone':
                        profile = config['profiles'].get(network['name'])
                        address = await asyncio.to_thread(self.phone_discoverer, profile, network) if profile else None
                        if generation != await self.observe(): return
                        if address != endpoint['host']: continue
                    remote, upstream = await asyncio.wait_for(asyncio.open_connection(endpoint['host'], endpoint['port']), config['connect_timeout'])
                    if generation != await self.observe(): return
                    self.selected = endpoint; self.write_status(); break
                except (OSError, asyncio.TimeoutError):
                    continue
            if upstream is None: return
            async def pump(source, destination):
                while True:
                    data = await source.read(65536)
                    if generation != self.generation: return
                    if not data:
                        if destination.can_write_eof(): destination.write_eof(); await destination.drain()
                        return
                    destination.write(data); await destination.drain()
            # Retry is only permitted before reading/forwarding ANY client bytes.
            pumps = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(remote, writer))]
            try:
                await asyncio.gather(*pumps)
            finally:
                for pending in pumps: pending.cancel()
                await asyncio.gather(*pumps, return_exceptions=True)
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            for connection in (upstream, writer):
                if connection:
                    connection.close()
                    with contextlib.suppress(OSError, asyncio.TimeoutError):
                        await asyncio.wait_for(connection.wait_closed(), 2)
            self.clients.discard(task)

    async def start(self, port=None, monitor=True):
        await self.refresh()
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', self.config['listen_port'] if port is None else port)
        if monitor:
            async def watch():
                while True:
                    await asyncio.sleep(1)
                    await self.refresh(force=False)
            self.monitor = asyncio.create_task(watch())
        return self.server

    async def close(self):
        if self.monitor:
            self.monitor.cancel(); await asyncio.gather(self.monitor, return_exceptions=True)
        if self.server:
            self.server.close(); await self.server.wait_closed()
        for task in list(self.clients): task.cancel()
        await asyncio.gather(*list(self.clients), return_exceptions=True)


def notify_ready():
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect('\x00' + address[1:] if address.startswith('@') else address)
            sock.sendall(b'READY=1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--status')
    parser.add_argument('--check-config', action='store_true')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    try:
        with open(args.config) as stream: validate_config(json.load(stream))
        if args.port is not None and not 1 <= args.port <= 65535: raise ValueError('invalid --port')
    except (OSError, ValueError, TypeError, KeyError):
        parser.error('invalid or unreadable configuration')
    if args.check_config:
        print('Configuration valid (loopback only; no connectivity check).'); return
    if not args.status: parser.error('--status is required when running')
    async def run():
        engine = Relay(args.config, args.status)
        try:
            await engine.start(port=args.port)
            notify_ready()
            async with engine.server: await engine.server.serve_forever()
        finally: await engine.close()
    try: asyncio.run(run())
    except KeyboardInterrupt: pass


if __name__ == '__main__': main()
