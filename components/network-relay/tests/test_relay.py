# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenJustSayAI

import asyncio
import importlib.util
import ipaddress
import json
import pathlib
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('relay', ROOT / 'relay.py')
relay = importlib.util.module_from_spec(spec) if spec else None
try:
    spec.loader.exec_module(relay)
except FileNotFoundError:
    relay = None


def sample_config():
    return {
        'mac': {'host': 'my-mac.local', 'port': 1082, 'enabled': True},
        'profiles': {
            'HomeWiFi': {'ip': '192.168.50.20', 'mac': '02:00:00:00:00:02', 'port': 2080,
                         'allowed_cidrs': ['192.168.50.0/24']},
            'OfficeWiFi': {'ip': '192.168.60.20', 'mac': '02:00:00:00:00:03', 'port': 2080,
                           'allowed_cidrs': ['192.168.60.0/24']},
            'PhoneHotspot': {'gateway': True, 'port': 2080},
        },
    }


def profile(name='HomeWiFi', **changes):
    raw = sample_config()
    raw['profiles'][name].update(changes)
    return relay.validate_config(raw)['profiles'][name]


class BaseTests(unittest.TestCase):
    def test_implementation_exists(self):
        self.assertIsNotNone(relay, 'relay.py must implement the tested contract')


@unittest.skipIf(relay is None, 'implementation absent')
class PacketTests(unittest.TestCase):
    def packet(self, mac='02:00:00:00:00:02', source='192.168.50.20', target='192.168.50.100'):
        sender = bytes.fromhex(mac.replace(':', ''))
        local = bytes.fromhex('001122334455')
        return local + sender + b'\x08\x06' + struct.pack('!HHBBH', 1, 0x800, 6, 4, 2) + sender + socket.inet_aton(source) + local + socket.inet_aton(target)

    def test_accept_only_matching_mac_local_target_and_subnet(self):
        args = ('02:00:00:00:00:02', '192.168.50.100', '192.168.50.0/24', '00:11:22:33:44:55')
        self.assertEqual(relay.parse_arp(self.packet(), *args), '192.168.50.20')
        self.assertIsNone(relay.parse_arp(self.packet(mac='aa:bb:cc:dd:ee:ff'), *args))
        self.assertIsNone(relay.parse_arp(self.packet(source='10.0.0.1'), *args))
        self.assertIsNone(relay.parse_arp(self.packet(target='192.168.50.101'), *args))
        self.assertIsNone(relay.parse_arp(b'bad', *args))
        malformed = bytearray(self.packet()); malformed[22] ^= 1
        self.assertIsNone(relay.parse_arp(malformed, *args))

    def test_phone_requires_matching_neighbor_identity(self):
        trusted=profile()
        network={'name':'HomeWiFi','interface':'wlan0','local':'192.168.50.100','prefix':24,'mac':'00:11:22:33:44:55'}
        reused=[{'dst':'192.168.50.20','lladdr':'aa:bb:cc:dd:ee:ff','state':['REACHABLE']}]
        with patch.object(relay,'command_json',return_value=reused), patch.object(relay.socket,'socket',side_effect=PermissionError):
            self.assertIsNone(relay.discover_phone(trusted,network))
        moved=reused+[{'dst':'192.168.50.90','lladdr':trusted['mac'],'state':['STALE']}]
        with patch.object(relay,'command_json',return_value=moved):
            self.assertEqual(relay.discover_phone(trusted,network),'192.168.50.90')
        with patch.object(relay,'command_json',return_value=moved) as command:
            self.assertIsNone(relay.discover_phone(trusted,dict(network,prefix=16)))
            command.assert_not_called()
            self.assertIsNone(relay.discover_phone(trusted,dict(network,name='airport')))
            command.assert_not_called()


    def test_real_linux_wifi_network_reads_actual_ssid_and_link_mac(self):
        address=[{'ifname':'wlan0','addr_info':[{'family':'inet','scope':'global','local':'192.168.50.63','prefixlen':24}]}]
        def command(args):
            if args[3:5]==['route','show']: return [{'dev':'wlan0','gateway':'192.168.50.1'}]
            if 'addr' in args: return address
            if 'link' in args: return [{'address':'00:11:22:33:44:55'}]
            raise AssertionError(args)
        def nmcli(args,**kwargs):
            if 'GENERAL.TYPE,GENERAL.CON-UUID' in args: return b'wifi\nprofile-uuid\n'
            if '802-11-wireless.ssid' in args:
                # Model nmcli's default terse escaping; callers need the literal SSID.
                raw = ssid if '--escape' in args and args[args.index('--escape')+1] == 'no' else ssid.replace('\\', '\\\\').replace(':', '\\:')
                return (raw+'\n').encode()
            raise AssertionError(args)
        for ssid in ('HomeWiFi', 'Home:WiFi', r'Home\WiFi', '家庭 Wi-Fi'):
            with self.subTest(ssid=ssid), patch.object(relay,'command_json',side_effect=command), patch.object(relay.subprocess,'check_output',side_effect=nmcli):
                network=relay.read_network()
                self.assertEqual(network['name'],ssid)
                self.assertEqual(network['mac'],'00:11:22:33:44:55')
        with patch.object(relay,'command_json',side_effect=command), patch.object(relay.subprocess,'check_output',return_value=b'ethernet\nprofile-uuid\n'):
            self.assertEqual(relay.read_network()['name'],'unknown')

    def test_discovery_rejects_wrong_trusted_profile_subnet_before_any_packet(self):
        trusted=profile()
        network={'name':'HomeWiFi','interface':'wlan0','local':'10.42.9.10','prefix':24,'mac':'00:11:22:33:44:55'}
        with patch.object(relay,'command_json') as command, patch.object(relay.socket,'socket') as packets:
            self.assertIsNone(relay.discover_phone(trusted,network))
            command.assert_not_called(); packets.assert_not_called()
        self.assertEqual(trusted['allowed_cidrs'], ['192.168.50.0/24'])
        for cidrs in ([], ['0.0.0.0/0'], ['10.0.0.0/8'], ['192.168.0.0/16'], ['8.8.8.0/24'], ['127.0.0.0/24'], ['169.254.1.0/24'], ['2001:db8::/64']):
            with self.assertRaises(ValueError): profile(allowed_cidrs=cidrs)

    def test_raw_discovery_builds_correct_requests_and_accepts_only_bound_interface(self):
        trusted=profile(ip='192.168.50.250')
        network={'name':'HomeWiFi','interface':'wlan0','local':'192.168.50.100','prefix':24,'mac':'00:11:22:33:44:55'}
        packet=self.packet()
        class PacketSocket:
            def __init__(self): self.sent=[]; self.replies=iter([(packet,('eth0',0)),(packet,('wlan0',0))])
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def bind(self,address): self.address=address
            def settimeout(self,timeout): pass
            def send(self,frame): self.sent.append(frame); return len(frame)
            def recvfrom(self,limit): return next(self.replies)
        raw=PacketSocket()
        with patch.object(relay.socket,'AF_PACKET',17,create=True), patch.object(relay.socket,'socket',return_value=raw), patch.object(relay,'command_json',return_value=[]):
            self.assertEqual(relay.discover_phone(trusted,network),'192.168.50.20')
        self.assertEqual(raw.address,('wlan0',0))
        self.assertLessEqual(len(raw.sent),254)
        self.assertEqual(raw.sent[0][-4:],socket.inet_aton('192.168.50.250'))
        for frame in raw.sent:
            self.assertEqual(len(frame),42)
            self.assertEqual(frame[:6],b'\xff'*6)
            self.assertEqual(frame[12:14],b'\x08\x06')
            self.assertEqual(frame[14:22],struct.pack('!HHBBH',1,0x800,6,4,1))
            self.assertEqual(frame[22:28],bytes.fromhex('001122334455'))
            self.assertEqual(frame[28:32],socket.inet_aton(network['local']))
            self.assertEqual(frame[32:38],b'\x00'*6)
            self.assertIn(ipaddress.IPv4Address(frame[-4:]),ipaddress.IPv4Network('192.168.50.0/24'))

    def test_raw_discovery_drains_queued_reply_even_when_send_budget_is_used(self):
        trusted=profile(ip='192.168.50.250')
        network={'name':'HomeWiFi','interface':'wlan0','local':'192.168.50.100','prefix':24,'mac':'00:11:22:33:44:55'}
        packet=self.packet()
        for block_first in (False,True):
            with self.subTest(block_first=block_first):
                clock=[100.0]
                class PacketSocket:
                    def __init__(self): self.calls=0; self.ready=False; self.sent=[]
                    def __enter__(self): return self
                    def __exit__(self,*args): pass
                    def bind(self,address): pass
                    def settimeout(self,timeout): pass
                    def send(self,frame):
                        self.calls+=1
                        if block_first and self.calls==1: raise BlockingIOError()
                        self.sent.append(frame); clock[0]+=3.0; self.ready=True
                        return len(frame)
                    def recvfrom(self,limit):
                        if not self.ready: raise BlockingIOError()
                        self.ready=False
                        return packet,('wlan0',0)
                raw=PacketSocket()
                def advance(delay): clock[0]+=delay
                with patch.object(relay.socket,'AF_PACKET',17,create=True), patch.object(relay.socket,'socket',return_value=raw), patch.object(relay,'command_json',return_value=[]), patch.object(relay.time,'monotonic',side_effect=lambda:clock[0]), patch.object(relay.time,'sleep',side_effect=advance):
                    self.assertEqual(relay.discover_phone(trusted,network),'192.168.50.20')
                self.assertLessEqual(clock[0]-100,3.5)
                self.assertEqual(raw.sent[0][-4:],socket.inet_aton('192.168.50.250'))
                self.assertEqual(raw.calls,2 if block_first else 1)

    def test_raw_discovery_reaches_late_dhcp_address_and_finishes_without_reply(self):
        trusted=profile(ip='192.168.50.250')
        network={'name':'HomeWiFi','interface':'wlan0','local':'192.168.50.100','prefix':24,'mac':'00:11:22:33:44:55'}
        packet=self.packet(source='192.168.50.226')
        for responds in (True,False):
            with self.subTest(responds=responds):
                clock=[100.0]
                class PacketSocket:
                    def __init__(self): self.sent=[]; self.timeout=0
                    def __enter__(self): return self
                    def __exit__(self,*args): pass
                    def bind(self,address): pass
                    def settimeout(self,timeout): self.timeout=timeout
                    def send(self,frame): self.sent.append((clock[0],frame)); return len(frame)
                    def recvfrom(self,limit):
                        if responds and any(frame[-4:]==socket.inet_aton('192.168.50.226') for _,frame in self.sent):
                            return packet,('wlan0',0)
                        if self.timeout: clock[0]+=self.timeout; raise socket.timeout()
                        raise BlockingIOError()
                raw=PacketSocket()
                def advance(delay): clock[0]+=delay
                with patch.object(relay.socket,'AF_PACKET',17,create=True), patch.object(relay.socket,'socket',return_value=raw), patch.object(relay,'command_json',return_value=[]), patch.object(relay.time,'monotonic',side_effect=lambda:clock[0]), patch.object(relay.time,'sleep',side_effect=advance):
                    self.assertEqual(relay.discover_phone(trusted,network),'192.168.50.226' if responds else None)
                self.assertLessEqual(clock[0]-100,3.5)
                self.assertLessEqual(len(raw.sent),254)
                for timestamp in {at for at,_ in raw.sent}:
                    self.assertLessEqual(sum(at==timestamp for at,_ in raw.sent),8)

    def test_systemd_notify_supports_absence_and_abstract_address(self):
        with patch.dict(relay.os.environ,{},clear=True), patch.object(relay.socket,'socket') as socket_factory:
            relay.notify_ready(); socket_factory.assert_not_called()
        with patch.dict(relay.os.environ,{'NOTIFY_SOCKET':'@reachy-ready'},clear=True), patch.object(relay.socket,'socket') as socket_factory:
            sock=socket_factory.return_value.__enter__.return_value
            relay.notify_ready()
            sock.connect.assert_called_once_with('\x00reachy-ready')
            sock.sendall.assert_called_once_with(b'READY=1')

    def test_empty_config_has_no_enabled_upstream_or_personal_defaults(self):
        config = relay.validate_config({})
        self.assertEqual(config['profiles'], {})
        self.assertEqual(config['mac'], {'host': 'localhost', 'port': 1082, 'enabled': False})

    def test_arbitrary_ssid_profiles_bind_to_the_actual_config_key(self):
        raw = {'profiles': {'Renamed Wi-Fi': {'ip': '10.42.9.20', 'mac': '02:00:00:00:00:02',
                'port': 2080, 'allowed_cidrs': ['10.42.9.0/24']}}}
        trusted = relay.validate_config(raw)['profiles']['Renamed Wi-Fi']
        network = {'name': 'Renamed Wi-Fi', 'interface': 'wlan0', 'local': '10.42.9.100',
                   'prefix': 24, 'mac': '00:11:22:33:44:55'}
        neighbors = [{'dst': '10.42.9.20', 'lladdr': trusted['mac'], 'state': ['REACHABLE']}]
        with patch.object(relay, 'command_json', return_value=neighbors):
            self.assertEqual(relay.discover_phone(trusted, network), '10.42.9.20')
        with patch.object(relay, 'command_json') as command, patch.object(relay.socket, 'socket') as packets:
            self.assertIsNone(relay.discover_phone(trusted, dict(network, name='HomeWiFi')))
            command.assert_not_called(); packets.assert_not_called()

    def test_explicit_office_subnet_and_smaller_private_networks_are_supported(self):
        self.assertEqual(profile('OfficeWiFi')['allowed_cidrs'], ['192.168.60.0/24'])
        self.assertEqual(profile(allowed_cidrs=['192.168.50.0/25'])['allowed_cidrs'], ['192.168.50.0/25'])
        for block, address in [('10.2.3.0/24', '10.2.3.20'), ('172.16.5.0/26', '172.16.5.20')]:
            self.assertEqual(profile(ip=address, allowed_cidrs=[block])['ip'], address)

    def test_hotspot_gateway_requires_its_own_ssid_and_private_active_subnet(self):
        trusted = profile('PhoneHotspot')
        network = {'name': 'PhoneHotspot', 'local': '192.168.80.2', 'prefix': 24,
                   'gateway': '192.168.80.1'}
        self.assertEqual(relay.discover_phone(trusted, network), '192.168.80.1')
        for changes in ({'name': 'airport'}, {'name': 'HomeWiFi'}, {'gateway': '8.8.8.8'},
                        {'gateway': '192.168.80.2'}, {'gateway': '192.168.80.0'},
                        {'gateway': '192.168.80.255'}, {'gateway': None}, {'prefix': 16},
                        {'local': '8.8.8.2', 'gateway': '8.8.8.1'}):
            self.assertIsNone(relay.discover_phone(trusted, dict(network, **changes)))

    def test_unknown_fields_credentials_and_incomplete_profiles_are_rejected(self):
        for changes in ({'password': 'example'}, {'_ssid': 'Other'}, {'gateway': True},
                        {'mac': 'invalid'}, {'ip': '8.8.8.8'}, {'ip': '192.168.60.20'},
                        {'ip': '192.168.50.0'}, {'ip': '192.168.50.255'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): profile(**changes)
        for name in ('', 42):
            with self.assertRaises(ValueError):
                relay.validate_config({'profiles': {name: {'gateway': True, 'port': 2080}}})
        for raw in ({'profiles': {'ssid': {}}}, {'mac': {'token': 'example'}},
                    {'profiles': {'ssid': {'gateway': False, 'port': 2080}}},
                    {'profiles': {'ssid': {'gateway': True, 'port': 2080, 'ip': '192.168.50.1'}}}):
            with self.subTest(raw=raw), self.assertRaises(ValueError): relay.validate_config(raw)

    def test_configuration_rejects_credentials_and_external_bind(self):
        config = relay.validate_config({})
        self.assertEqual(config['listen_port'], 18080)
        for changes in ({'listen_host':'0.0.0.0'}, {'mac':{'host':'http://user:secret@host'}}, {'profiles':{'unknown':{'gateway':True}}}, {'listen_port':0}):
            with self.assertRaises(ValueError): relay.validate_config(changes)


@unittest.skipIf(relay is None, 'implementation absent')
class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = pathlib.Path(self.temp.name)/'config.json'
        self.status = pathlib.Path(self.temp.name)/'status.json'
        self.servers=[]
        self.connections=[]
        self.config.write_text('{}')
        self.network = {'name':'HomeWiFi','interface':'wlan0','local':'192.168.50.100','prefix':24,'gateway':'192.168.50.1','mac':'00:11:22:33:44:55'}
        self.engine = relay.Relay(str(self.config), str(self.status), network_reader=lambda:self.network, health_checker=lambda endpoint,timeout:True, phone_discoverer=lambda profile,network:'127.0.0.1' if profile.get('ip') else None)

    async def asyncTearDown(self):
        for writer in self.connections:
            writer.close()
        for server in self.servers:
            server.close(); await server.wait_closed()
        await self.engine.close()
        self.temp.cleanup()

    async def proxy(self, behavior=None):
        received=[]
        async def handle(reader,writer):
            self.connections.append(writer)
            try:
                if behavior:
                    await behavior(reader,writer,received)
                else:
                    data=await reader.read(); received.append(data)
                    writer.write(data[::-1]); await writer.drain()
            finally:
                writer.close()
                try: await writer.wait_closed()
                except ConnectionResetError: pass
        server=await asyncio.start_server(handle,'127.0.0.1',0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1], received

    def configure(self, macport, phoneport=2080, enabled=True):
        raw = sample_config()
        raw['mac'] = {'host': '127.0.0.1', 'port': macport, 'enabled': enabled}
        for endpoint in raw['profiles'].values(): endpoint['port'] = phoneport
        self.config.write_text(json.dumps(raw))

    async def connect(self, connector=None):
        if not self.engine.server:
            await self.engine.start(port=0, monitor=False)
        return await (connector or asyncio.open_connection)('127.0.0.1',self.engine.server.sockets[0].getsockname()[1])

    async def request(self, body):
        reader,writer=await self.connect()
        self.connections.append(writer)
        writer.write(body); await writer.drain(); writer.write_eof()
        try: result=await asyncio.wait_for(reader.read(),2)
        except ConnectionResetError: result=b''
        writer.close()
        try: await writer.wait_closed()
        except ConnectionResetError: pass
        return result

    async def test_empty_config_closes_without_attempting_an_upstream(self):
        with patch.object(self.engine, 'health_checker') as health, patch.object(self.engine, 'phone_discoverer') as discover:
            await self.engine.refresh()
            self.assertEqual(self.engine.healthy, [])
            health.assert_not_called(); discover.assert_not_called()
        await self.engine.start(port=0, monitor=False)
        with patch.object(relay.asyncio, 'open_connection') as upstream:
            # Use the original connector for the client, while spying on relay upstreams.
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.create_connection(lambda: protocol, '127.0.0.1', self.engine.server.sockets[0].getsockname()[1])
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            self.connections.append(writer)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
            upstream.assert_not_called()

    async def test_opaque_bytes_and_half_close(self):
        port,received=await self.proxy(); self.configure(port)
        await self.engine.refresh()
        body=b'CONNECT host:443 HTTP/1.1\r\n\r\n\x00\xffopaque'
        self.assertEqual(await self.request(body),body[::-1])
        self.assertEqual(received,[body])
        status=json.loads(self.status.read_text())
        self.assertEqual(status['selected']['name'],'mac')
        self.assertNotIn('CONNECT',self.status.read_text())

    async def test_connect_failure_tries_next_healthy(self):
        port,received=await self.proxy()
        closed=socket.socket(); closed.bind(('127.0.0.1',0)); unavailable=closed.getsockname()[1]; closed.close()
        self.configure(unavailable,port); await self.engine.refresh()
        self.assertEqual(await self.request(b'payload'),b'daolyap')
        self.assertEqual(received,[b'payload'])
        self.assertEqual(json.loads(self.status.read_text())['selected']['name'],'phone')

    async def test_no_healthy_proxy_closes_without_direct_fallback(self):
        port,received=await self.proxy(); self.configure(port)
        self.engine.health_checker=lambda endpoint,timeout:False
        await self.engine.refresh()
        self.assertEqual(await self.request(b'payload'),b'')
        self.assertEqual(received,[])

    async def test_cached_phone_health_cannot_use_reassigned_address(self):
        port,received=await self.proxy(); self.configure(port,port,False)
        await self.engine.start(port=0,monitor=False)
        self.assertEqual(len(self.engine.healthy),1)
        self.engine.phone_discoverer=lambda profile,network:None
        self.assertEqual(await self.request(b'should not reach reused phone IP'),b'')
        self.assertEqual(received,[])

    async def test_do_not_replay_after_upstream_disconnect(self):
        async def consume(reader,writer,received):
            received.append(await reader.read(100))
        macport,macdata=await self.proxy(consume)
        phoneport,phonedata=await self.proxy()
        self.configure(macport,phoneport); await self.engine.refresh()
        await self.request(b'one request')
        self.assertEqual(macdata,[b'one request']); self.assertEqual(phonedata,[])

    async def test_config_reload_disables_mac_and_network_change_discards_health(self):
        macport,macdata=await self.proxy(); phoneport,phonedata=await self.proxy()
        self.configure(macport,phoneport); await self.engine.refresh()
        self.assertEqual(await self.request(b'first'),b'tsrif')
        self.configure(macport,phoneport,False); await self.engine.refresh()
        self.assertEqual(await self.request(b'second'),b'dnoces')
        self.network=dict(self.network,name='OfficeWiFi')
        calls=[]
        self.engine.phone_discoverer=lambda profile,network:calls.append(network['name']) or '127.0.0.1'
        self.engine.health_checker=lambda endpoint,timeout:False
        await self.engine.refresh()
        self.assertEqual(self.engine.healthy,[]); self.assertEqual(calls,['OfficeWiFi'])
        self.assertEqual(json.loads(self.status.read_text())['network']['name'],'OfficeWiFi')

    async def test_health_check_sends_connect_and_rejects_plaintext_tls(self):
        async def not_tls(reader,writer,received):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n'); await writer.drain()
            received.append(await reader.read(1000))
            writer.write(b'HTTP/1.1 200 OK\r\n\r\n'); await writer.drain()
        port,received=await self.proxy(not_tls)
        result=relay.check_proxy({'host':'127.0.0.1','port':port},0.3)
        self.assertTrue(asyncio.iscoroutine(result),'default health check must be cancellable')
        self.assertFalse(await result)
        self.assertIn(b'CONNECT huggingface.co:443 HTTP/1.',received[0])
        self.assertNotIn(b'HEAD',received[1])

    async def test_health_timeout_does_not_stall_refresh(self):
        async def hangs(endpoint, timeout):
            await asyncio.sleep(2)
            return True
        self.config.write_text(json.dumps({'health_timeout':0.03,'mac':{'enabled':True}}))
        self.engine.health_checker=hangs
        self.network={'name':'airport'}
        await asyncio.wait_for(self.engine.refresh(),0.5)
        self.assertEqual(self.engine.healthy,[])

    async def test_long_lived_bidirectional_stream(self):
        async def echo(reader,writer,received):
            while data:=await reader.read(100):
                received.append(data); writer.write(data); await writer.drain()
        port,received=await self.proxy(echo); self.configure(port); await self.engine.refresh()
        reader,writer=await self.connect(); self.connections.append(writer)
        for data in (b'first',b'\x00\xffsecond'):
            writer.write(data); await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)),1),data)
        writer.write_eof(); self.assertEqual(await asyncio.wait_for(reader.read(),1),b'')


    async def test_discovery_completion_cannot_connect_after_generation_invalidated(self):
        port,_=await self.proxy(); self.configure(port,port,False)
        await self.engine.start(port=0,monitor=False)
        entered=threading.Event(); release=threading.Event()
        def delayed(profile,network):
            entered.set(); release.wait(2); return '127.0.0.1'
        self.engine.phone_discoverer=delayed
        pending=asyncio.create_task(self.request(b'stale'))
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        self.network=dict(self.network,name='airport')
        with patch.object(relay.asyncio,'open_connection') as connection:
            try:
                await self.engine.refresh(); release.set()
                try: await pending
                except (ConnectionError,asyncio.CancelledError): pass
                await asyncio.sleep(0.03)
                connection.assert_not_called()
            finally: release.set()

    async def test_network_change_during_discovery_is_observed_before_connect(self):
        port,_=await self.proxy(); self.configure(port,port,False)
        await self.engine.start(port=0,monitor=False)
        entered=threading.Event(); release=threading.Event()
        def delayed(profile,network):
            entered.set(); release.wait(2); return '127.0.0.1'
        self.engine.phone_discoverer=delayed
        pending=asyncio.create_task(self.request(b'stale'))
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        self.network=dict(self.network,name='airport')
        with patch.object(relay.asyncio,'open_connection') as connection:
            release.set()
            try: await pending
            except ConnectionError: pass
            connection.assert_not_called()

    async def test_network_change_during_connect_is_observed_before_forwarding(self):
        port,received=await self.proxy(); self.configure(port)
        await self.engine.start(port=0,monitor=False)
        original=asyncio.open_connection
        async def changing(*args,**kwargs):
            result=await original(*args,**kwargs)
            self.network=dict(self.network,name='airport')
            return result
        with patch.object(relay.asyncio,'open_connection',side_effect=changing):
            # Install the upstream hook before the server can accept the client.
            reader,writer=await self.connect(connector=original); self.connections.append(writer)
            writer.write(b'stale'); await writer.drain()
            try: data=await asyncio.wait_for(reader.read(),1)
            except ConnectionResetError: data=b''  # Closing unread TCP bytes may send RST.
            self.assertEqual(data,b'')
        await asyncio.sleep(.03)
        self.assertEqual(received,[b''])

    async def test_observed_network_change_triggers_immediate_health_refresh(self):
        port,_=await self.proxy(); self.configure(port)
        await self.engine.refresh()
        self.network=dict(self.network,name='OfficeWiFi')
        await self.engine.observe()
        self.assertEqual(self.engine.healthy,[])
        await self.engine.refresh(force=False)
        self.assertTrue(self.engine.healthy)

    async def test_delayed_connection_cannot_forward_after_invalidation(self):
        port,_=await self.proxy(); self.configure(port)
        await self.engine.start(port=0,monitor=False)
        entered=asyncio.Event(); release=asyncio.Event()
        original=asyncio.open_connection
        attempts=[]
        async def delayed(*args,**kwargs):
            attempts.append((args,kwargs))
            entered.set(); await release.wait()
            return await original(*args,**kwargs)
        with patch.object(relay.asyncio,'open_connection',side_effect=delayed):
            reader,writer=await self.connect(connector=original); self.connections.append(writer)
            writer.write(b'stale'); await writer.drain()
            await asyncio.wait_for(entered.wait(),1)
            self.network=dict(self.network,name='airport')
            self.engine.health_checker=lambda endpoint,timeout:False
            await self.engine.refresh(); release.set()
            try: data=await asyncio.wait_for(reader.read(),1)
            except ConnectionResetError: data=b''
            self.assertEqual(data,b'')
        self.assertEqual(len(attempts),1)

    async def test_stale_health_completion_cannot_repopulate_candidates(self):
        entered=asyncio.Event(); release=asyncio.Event()
        async def delayed(endpoint,timeout):
            entered.set(); await release.wait(); return True
        self.engine.health_checker=delayed
        self.config.write_text(json.dumps({'mac': {'enabled': True}}))
        self.network={'name':'airport'}
        pending=asyncio.create_task(self.engine.refresh())
        await asyncio.wait_for(entered.wait(),1)
        self.config.write_text(json.dumps({'mac':{'enabled':False}}))
        await self.engine.refresh(); release.set(); await pending
        self.assertEqual(self.engine.healthy,[])

    async def test_each_connection_reads_network_and_invalidates_existing_stream(self):
        entered=asyncio.Event(); received=[]
        async def collect(reader,writer,_):
            received.append(await reader.read(5)); entered.set()
            received.append(await reader.read())
        port,_=await self.proxy(collect); self.configure(port)
        await self.engine.start(port=0,monitor=False)
        reader,writer=await self.connect(); self.connections.append(writer)
        writer.write(b'first'); await writer.drain(); await asyncio.wait_for(entered.wait(),1)
        self.network=dict(self.network,name='airport')
        self.engine.health_checker=lambda endpoint,timeout:False
        self.assertEqual(await self.request(b'new'),b'')
        self.assertEqual(await asyncio.wait_for(reader.read(),1),b'')
        await asyncio.sleep(0.03)
        self.assertEqual(received,[b'first',b''])

    async def test_unknown_network_never_invents_phone_gateway(self):
        self.network=dict(self.network,name='airport')
        self.config.write_text(json.dumps({'mac':{'enabled':False}}))
        await self.engine.refresh()
        self.assertEqual(self.engine.healthy,[])


if __name__=='__main__': unittest.main()
