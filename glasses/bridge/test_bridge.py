"""Tests on made-up data only: no network, no Claude session, no Kit state of this Mac.

    /usr/bin/python3 -m unittest discover -s glasses/bridge -p 'test_*.py'
"""
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import detail  # noqa: E402
import kitstate  # noqa: E402
import stt  # noqa: E402
import wsock  # noqa: E402


def ev(n, payload, source='worker'):
    return {'sequence_num': str(n), 'source': source, 'payload': payload}


QUESTION = {'type': 'control_request', 'request_id': 'r1', 'request': {
    'subtype': 'can_use_tool', 'tool_name': 'AskUserQuestion', 'tool_use_id': 'tu1',
    'input': {'questions': [
        {'question': 'Which press?', 'header': 'Press', 'multiSelect': False,
         'options': [{'label': 'Press 3'}, {'label': 'Press 5'}]},
        {'question': 'Which shift?', 'header': 'Shift', 'multiSelect': True,
         'options': [{'label': 'Day'}, {'label': 'Night'}]}]}}}


class Plain(unittest.TestCase):
    def test_marks_go_and_code_stays(self):
        md = ('# Press 3 ink check\n\nThe **cyan** head is _clogged_; see [the log](https://example.com/log).\n\n'
              '- Purge it\n- Print the `nozzle_check` page\n\n```bash\nrun --head **cyan**\n```\n\n'
              '| Head | State |\n|---|---|\n| C | clogged |\n\n> Done by **noon**.')
        out = detail.plain(md)
        self.assertEqual(out, 'Press 3 ink check\n\nThe cyan head is clogged; see the log.\n\n- Purge it\n'
                              '- Print the nozzle_check page\n\nrun --head **cyan**\n\nHead | State\nC | clogged\n\n'
                              'Done by noon.')

    def test_underscores_in_words_stay(self):
        self.assertEqual(detail.plain('set max_speed in job_ticket_3'), 'set max_speed in job_ticket_3')


class Pending(unittest.TestCase):
    def test_open_question_found(self):
        evs = [ev(5, QUESTION), ev(4, {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Hi'}]}})]
        req = detail.find_pending(evs)
        self.assertEqual(req['request_id'], 'r1')
        self.assertEqual(detail.last_reply(evs), 'Hi')

    def test_answered_withdrawn_or_ended(self):
        answered = [ev(6, {'type': 'control_response', 'response': {'request_id': 'r1'}}, 'client'), ev(5, QUESTION)]
        withdrawn = [ev(6, {'type': 'control_cancel_request', 'request_id': 'r1'}), ev(5, QUESTION)]
        ended = [ev(7, {'type': 'result'}), ev(5, QUESTION)]
        for evs in (answered, withdrawn, ended):
            self.assertIsNone(detail.find_pending(evs))

    def test_two_questions_answer_after_the_last(self):
        req = detail.find_pending([ev(5, QUESTION)])
        v = detail.view(req)
        self.assertEqual(v['kind'], 'question')
        self.assertEqual(v['text'], '(1/2) Which press?')
        self.assertEqual([o['id'] for o in v['options']], ['q0.o0', 'q0.o1'])
        done, partial, *_ = detail.decide(req, 'q0.o1')
        self.assertFalse(done)
        self.assertEqual(detail.view(req, partial)['text'], '(2/2) Which shift?')
        done, partial, behavior, upd, _ = detail.decide(req, 'q1.o0', partial)
        self.assertTrue(done)
        self.assertEqual(behavior, 'allow')
        self.assertEqual(upd['answers'], {'Which press?': 'Press 5', 'Which shift?': ['Day']})
        self.assertEqual(len(upd['questions']), 2)
        with self.assertRaises(detail.BadOption):
            detail.decide(req, 'q9.o0')

    def test_plan_and_permission(self):
        plan = {'request_id': 'p', 'tool_name': 'ExitPlanMode', 'input': {'plan': '## Plan\n1. **Purge** head'}}
        self.assertEqual(detail.view(plan)['text'], 'Plan\n1. Purge head')
        self.assertEqual(detail.decide(plan, 'keep')[2], 'deny')
        perm = {'request_id': 'q', 'tool_name': 'Bash', 'display_name': 'Bash', 'input': {'command': 'ls'}}
        self.assertEqual(detail.view(perm)['text'], 'Allow Bash? ls')
        self.assertEqual(detail.decide(perm, 'allow')[3], {'command': 'ls'})


class Status(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        state = {'sessions': {
            'cse_a': {'title': 'Quote for press 5', 'app': {'needs': True, 'why': 'It asks which supplier',
                                                           'last_event_at': '2026-01-05T10:00:00Z'}},
            'cse_b': {'title': 'Line 2 maintenance'}},
            'waits': {'w1': {'id': 'w1', 'cse': 'cse_c', 'what': 'Supplier quote', 'from': 'example.com',
                             'by': '1999999999'}}}
        with open(os.path.join(self.dir, 'state.json'), 'w') as f:
            json.dump(state, f)
        self.kit = kitstate.KitState(self.dir)
        self.kit.reload()

    def s(self, cse, **kw):
        base = {'id': cse, 'status': 'active', 'environment_id': 'env_x', 'connection_status': 'connected',
                'worker_status': 'idle', 'last_event_at': '2026-01-05T10:00:00Z', 'title': cse}
        base.update(kw)
        return base

    def test_groups(self):
        rows = [kitstate.summarize(x, self.kit) for x in (
            self.s('cse_a', unread=True),
            self.s('cse_b', worker_status='running', last_event_at='2026-01-05T11:00:00Z'),
            self.s('cse_c'),
            self.s('cse_d', last_event_at='2026-01-05T12:00:00Z'),
            self.s('cse_e', worker_status='requires_action', external_metadata={'pending_action': {
                'tool_name': 'AskUserQuestion', 'input': {'questions': [{'question': 'Which roll?'}]}}}))]
        by = {r['id']: r for r in rows}
        self.assertEqual(by['cse_a']['status'], 'needs_you')
        self.assertEqual(by['cse_a']['why'], 'It asks which supplier')
        self.assertEqual(by['cse_b']['status'], 'working')
        self.assertEqual(by['cse_c']['status'], 'waiting')
        self.assertEqual(by['cse_c']['why'], 'Supplier quote · from example.com')
        self.assertEqual(by['cse_d']['status'], 'idle')
        self.assertEqual(by['cse_e']['status'], 'needs_you')
        self.assertTrue(by['cse_e']['has_pending'])
        self.assertEqual(by['cse_e']['why'], 'Question: Which roll?')
        order = [r['id'] for r in kitstate.ordered(rows)]
        self.assertEqual(order, ['cse_e', 'cse_a', 'cse_b', 'cse_c', 'cse_d'])

    def test_read_reply_no_longer_needs_you(self):
        self.assertEqual(kitstate.summarize(self.s('cse_a', unread=False), self.kit)['status'], 'idle')

    def test_listed(self):
        self.assertTrue(kitstate.listed(self.s('cse_a')))
        self.assertTrue(kitstate.listed(self.s('cse_a', connection_status='disconnected')))
        self.assertFalse(kitstate.listed(self.s('cse_a', environment_id='', connection_status='disconnected')))
        self.assertFalse(kitstate.listed(self.s('cse_a', status='archived')))
        self.assertFalse(kitstate.listed(self.s('cse_a', trigger_id='trig_1')))


class Socket(unittest.TestCase):
    def test_masked_text_ping_and_reply(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        rfile = a.makefile('rb')
        self.addCleanup(rfile.close)
        ws = wsock.WebSocket(a, rfile)
        mask = b'\x01\x02\x03\x04'
        data = json.dumps({'type': 'subscribe', 'id': 'cse_x'}).encode()
        b.sendall(bytes([0x89, 0x80]) + mask)  # a ping with no data
        b.sendall(bytes([0x81, 0x80 | len(data)]) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))
        self.assertEqual(json.loads(ws.receive()), {'type': 'subscribe', 'id': 'cse_x'})
        self.assertEqual(b.recv(2), bytes([0x8A, 0]))  # the pong
        ws.send_json({'type': 'pong'})
        head = b.recv(2)
        self.assertEqual(head[0], 0x81)
        self.assertEqual(json.loads(b.recv(head[1])), {'type': 'pong'})
        self.assertEqual(wsock.accept_key('dGhlIHNhbXBsZSBub25jZQ=='), 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')


class Audio(unittest.TestCase):
    def test_wav_header(self):
        w = stt.wav(b'\x01\x00' * 16000)
        self.assertEqual(w[:4], b'RIFF')
        self.assertEqual(struct.unpack('<I', w[24:28])[0], 16000)
        self.assertEqual(struct.unpack('<I', w[40:44])[0], 32000)


if __name__ == '__main__':
    unittest.main()
