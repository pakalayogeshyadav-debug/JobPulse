import contextlib
import sys
import types

fcntl = types.ModuleType('fcntl')
fcntl.ioctl = lambda *args, **kwargs: None
fcntl.flock = lambda *args, **kwargs: None
fcntl.lockf = lambda *args, **kwargs: None
fcntl.LOCK_EX = 2; fcntl.LOCK_SH = 1; fcntl.LOCK_NB = 4; fcntl.LOCK_UN = 8
sys.modules['fcntl'] = fcntl

@contextlib.contextmanager
def mock_timeout(*args, **kwargs): yield
import airflow.utils.db

airflow.utils.db.timeout_with_traceback = mock_timeout

sys.path.insert(0, 'src')
from airflow.models import DagBag

d = DagBag('dags')
import pprint

pprint.pprint(d.import_errors)
