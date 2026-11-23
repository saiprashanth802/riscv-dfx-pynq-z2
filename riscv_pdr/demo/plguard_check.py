import sys, types; import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_server as s
calls = []
s.FAKE = False; s.LDR = types.SimpleNamespace(read_dmem=lambda *a: calls.append(a) or [0])
s._pl_base = '/home/xilinx/jupyter_notebooks/riscv_pdr/b3'
s._pl_owner = lambda: '/home/xilinx/jupyter_notebooks/other/overlays/other.bit'
for p in ('api/status', 'api/read'): assert s.api('GET', '/' + p)[0] == 409, p
for p in ('api/swap?to=bitwise', 'api/program', 'api/run', 'api/rick'): assert s.api('POST', '/' + p)[0] == 409, p
assert s.api('GET', '/api/loader')[0] == 200       # no AXI: still answers
s._pl_owner = lambda: s._pl_base + '/./config2.bit'
assert s._pl_ours()
s._pl_base = None; assert not s._pl_ours()          # nothing loaded by us
assert not calls, calls
print('plguard ok')
