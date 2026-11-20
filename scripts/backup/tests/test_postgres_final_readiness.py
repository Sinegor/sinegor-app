"""Regressions for the bootstrap Unix-socket readiness race; synthetic Docker only."""
import importlib.util
import itertools
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

TOOL = Path(os.environ.get('RESTORE_HELPER_UNDER_TEST', '/home/sinegoradmin/apps/sinegor-app/scripts/backup/restore_acceptance.py'))
ID = 'd' * 64
IMAGE = 'sha256:' + 'a' * 64
RUN = 'a' * 12

class ReachedDatabaseCreation(Exception):
    pass

class PostgresFinalServerReadinessTests(unittest.TestCase):
    def run_readiness(self, *, never_ready=False):
        spec=importlib.util.spec_from_file_location('restore_readiness_test_subject',TOOL)
        tool=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        state={'stable_tcp':False,'tcp_attempts':0,'create_attempted':False,'safe_at_create':False,'error':None}
        with tempfile.TemporaryDirectory() as temporary:
            fixture=types.SimpleNamespace(private=Path(temporary),run_id=RUN,environment={})
            pg={'id':ID,'name':'sinegor-backup-test-'+RUN}
            fixture.create=lambda *a,**k:pg
            fixture.start=lambda *a,**k:None
            fixture.inspect=lambda *a,**k:None
            def sql(database,query,**kwargs):
                if query=='SELECT 1':
                    # The bootstrap server already answers local Unix-socket queries.
                    return b'1'
                if query.startswith('CREATE DATABASE '):
                    state['create_attempted']=True
                    state['safe_at_create']=state['stable_tcp']
                    raise ReachedDatabaseCreation()
                raise AssertionError('Unexpected fixture SQL')
            fixture.sql=sql
            def call(command,**kwargs):
                words=[str(x) for x in command]
                if words[:3]==['docker','image','inspect']:
                    return json.dumps([{'Id':words[-1]}]).encode()
                if words[:2]==['docker','exec'] and 'pg_isready' in words:
                    state['tcp_attempts']+=1
                    host=words[words.index('-h')+1] if '-h' in words else None
                    port=words[words.index('-p')+1] if '-p' in words else None
                    if host!='127.0.0.1' or port!='5432':
                        # A socket check would incorrectly accept the bootstrap server.
                        return b''
                    if never_ready or state['tcp_attempts']<3:
                        raise tool.AcceptanceError('ToolFailed')
                    state['stable_tcp']=True
                    return b''
                raise AssertionError('Unexpected helper command')
            args=types.SimpleNamespace(postgres_image=IMAGE,api_image=IMAGE,cms_image=IMAGE)
            clock=itertools.count(0,31 if never_ready else 1)
            with patch.object(tool,'call',side_effect=call),patch.object(tool.time,'sleep'),patch.object(tool.time,'monotonic',side_effect=lambda:next(clock)):
                try:
                    tool.acceptance(args,fixture,tool.new_report())
                except ReachedDatabaseCreation:
                    pass
                except tool.AcceptanceError as error:
                    state['error']=str(error)
        return state

    def test_bootstrap_socket_success_cannot_authorize_database_creation(self):
        state=self.run_readiness()
        self.assertTrue(state['create_attempted'])
        self.assertTrue(state['safe_at_create'], 'CREATE DATABASE raced the bootstrap server shutdown')
        self.assertIsNone(state['error'])

    def test_unready_final_server_times_out_without_creating_databases(self):
        state=self.run_readiness(never_ready=True)
        self.assertFalse(state['create_attempted'], 'CREATE DATABASE must wait for the final TCP listener')
        self.assertEqual(state['error'],'PostgresReadinessTimeout')

if __name__=='__main__':
    unittest.main()
