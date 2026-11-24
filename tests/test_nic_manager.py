from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
"""Offline regression checks: never authenticate or change Windows adapters."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import importlib
import os

HERE = Path(__file__).resolve().parent


class NicRegression(unittest.TestCase):
    def test_manual_selection_of_usb_with_unknown_media_survives_restart(self):
        import nic_manager as nm
        usb = dict(device=r'\Device\NPF_{USB}', name='USB LAN', status='Up', wired=False,
                   selectable=True, ip='10.0.0.5')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(nm, 'inventory', return_value={'adapters': [usb]}), patch.object(nm, 'capture_devices', return_value={usb['device']}):
                nm.resolve_nic(base=base, force=True, preferred=usb['device'])
                self.assertEqual(nm.resolve_nic(base=base, force=True)['device'], usb['device'])

    def test_usb_not_marked_physical_is_still_enumerated(self):
        import subprocess
        import json
        script = ROOT / 'app' / 'getnic.ps1'
        fixture = r'''
function Get-NetAdapter {
    param([switch]$Physical)
    if ($Physical) { return }
    [pscustomobject]@{ Name='USB LAN'; InterfaceDescription='USB Ethernet'; Status='Up';
        NdisPhysicalMedium=0; MediaType='Unknown'; InterfaceType=6; ifIndex=17;
        InterfaceGuid='11111111-2222-3333-4444-555555555555'; PnPDeviceID='USB\VID_TEST' }
}
function Get-NetIPAddress { }
function Find-NetRoute { }
function Get-Process { }
'''
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'fixture.ps1'
            wrapper.write_text(fixture + "\n. '" + str(script).replace("'", "''") + "' -Inventory\n", encoding='utf-8-sig')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            adapters = json.loads(result.stdout.decode('utf-8-sig'))['adapters']
            self.assertEqual(len(adapters), 1)
            self.assertTrue(adapters[0]['wired'])

    def test_selection_on_another_computer_and_multiple_adapters(self):
        from nic_manager import select_adapter, NicError
        first = dict(device=r'\Device\NPF_{A}', name='USB Ethernet', status='Up', wired=True, ip='10.0.0.2')
        second = dict(device=r'\Device\NPF_{B}', name='Ethernet', status='Up', wired=True, ip='10.0.1.2')
        wifi = dict(device=r'\Device\NPF_{W}', name='WLAN', status='Up', wired=False, ip='10.0.2.2')
        self.assertEqual(select_adapter([wifi, first], r'\Device\NPF_{OLD}')['device'], first['device'])
        self.assertEqual(select_adapter([first, second], second['device'])['device'], second['device'])
        with self.assertRaises(NicError):
            select_adapter([first, second], '')
        with self.assertRaises(NicError):
            select_adapter([wifi, dict(first, status='Disconnected')], first['device'])

    def test_no_fallback_to_wifi_or_invisible_capture_device(self):
        import nic_manager as nm
        first = dict(device=r'\Device\NPF_{A}', name='Ethernet', status='Up', wired=True, ip='')
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(nm, 'inventory', return_value={'adapters': [first]}), patch.object(nm, 'capture_devices', return_value=set()):
                with self.assertRaises(nm.NicError):
                    nm.resolve_nic(base=Path(directory), force=True)
                self.assertFalse((Path(directory) / 'nic.txt').exists())
            with patch.object(nm, 'inventory', return_value={'adapters': [first]}), patch.object(nm, 'capture_devices', return_value={first['device']}):
                selected = nm.resolve_nic(base=Path(directory), force=True)
                self.assertEqual(selected['device'], first['device'])
                self.assertEqual((Path(directory) / 'nic.txt').read_text().strip(), first['device'])

    def test_scheduler_revalidates_stale_device_before_authentication(self):
        # A different computer must not inherit the sender's device identity.
        stage = ROOT / 'app'
        path = Path(stage) / 'auto_switch.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'read_nic')
        with tempfile.TemporaryDirectory() as directory:
            cached = Path(directory) / 'nic.txt'
            cached.write_text(r'\Device\NPF_{OLD-COMPUTER}', encoding='ascii')
            namespace = {'NIC': str(cached), 'BASE': directory,
                         'resolve_nic': lambda **kwargs: {'device': r'\Device\NPF_{CURRENT}'}}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
            self.assertEqual(namespace['read_nic'](), r'\Device\NPF_{CURRENT}')


if __name__ == '__main__':
    unittest.main()
