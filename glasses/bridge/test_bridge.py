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
import glance  # noqa: E402
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
                              '- Print the nozzle_check page\n\nrun --head **cyan**\n\nC\n  State: clogged\n\n'
                              'Done by noon.')

    def test_underscores_in_words_stay(self):
        self.assertEqual(detail.plain('set max_speed in job_ticket_3'), 'set max_speed in job_ticket_3')


class Tables(unittest.TestCase):
    """The lens font is proportional: each table row becomes a card, the header names its labels."""

    def test_status_table_goes_into_the_label(self):
        md = ('Where the press jobs stand:\n\n'
              '| Job | Status | Need from you |\n'
              '| --- | :---: | --- |\n'
              '| Job 4471 gloss wine labels | 🔴 | Pick the cyan head fix, and I start it. |\n'
              '| **Job 4480** coffee bags | 🔄 | Nothing |\n'
              '| Job 4475 reprint | ✅ | None |\n'
              '| Job 4462 sample run | ⚪️ | - |\n'
              '| Job 4490 proof | 🔴 Needs you | Tell me a day and time for the press check. |\n\n'
              'Two need you.')
        self.assertEqual(detail.plain(md),
                         'Where the press jobs stand:\n\n'
                         'Job 4471 gloss wine labels\n  Needs you: Pick the cyan head fix, and I start it.\n\n'
                         'Job 4480 coffee bags\n  In progress\n\n'
                         'Job 4475 reprint\n  Done\n\n'
                         'Job 4462 sample run\n  Dropped\n\n'
                         'Job 4490 proof\n  Needs you: Tell me a day and time for the press check.\n\n'
                         'Two need you.')

    def test_supplier_quote_labels_every_cell(self):
        md = ('| Supplier | Price | Lead time | Notes |\n|---|---|---|---|\n'
              '| New Star Labels | $0.12 per m | 3 weeks | n/a |\n'
              '| Harbor Film Co. | $0.10 per m | 6 weeks | Matte only<br>no gloss |')
        self.assertEqual(detail.plain(md),
                         'New Star Labels\n  Price: $0.12 per m\n  Lead time: 3 weeks\n\n'
                         'Harbor Film Co.\n  Price: $0.10 per m\n  Lead time: 6 weeks\n  Notes: Matte only no gloss')

    def test_numbers_status_and_more_columns(self):
        md = ('| # | Job | Status | Press | Due |\n|-|-|-|-|-|\n'
              '| 1 | Job 4471 | 🔄 Waiting on ink | 3 | Friday |\n'
              '| 2 | Job 4480 | ✅ | | |')
        self.assertEqual(detail.plain(md),
                         '1. Job 4471\n  Status: In progress, Waiting on ink\n  Press: 3\n  Due: Friday\n\n'
                         '2. Job 4480\n  Status: Done')

    def test_status_column_found_by_its_marks(self):
        md = '| | Part | Need from you |\n|--|--|--|\n| ✅ | Rewinder 2 belts | Nothing |\n| 🔴 | Laminate | Pick 5,000 m or 8,000 m |'
        self.assertEqual(detail.plain(md), 'Rewinder 2 belts\n  Done\n\nLaminate\n  Needs you: Pick 5,000 m or 8,000 m')

    def test_not_a_table(self):
        self.assertEqual(detail.plain('Heads 2 | 4 are clean'), 'Heads 2 | 4 are clean')
        self.assertEqual(detail.plain('Press 3 | Press 5\n---\nBoth run.'), 'Press 3 | Press 5\n\nBoth run.')

    def test_status_marks_in_lists(self):
        self.assertEqual(detail.plain('- ✅ Belts came in\n- 🔴 Pick the laminate'), '- Done, Belts came in\n- Needs you, Pick the laminate')


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


def said(n, text, **kw):
    return ev(n, dict({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}}, **kw))


def tool(n, **kw):
    return ev(n, dict({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
                                                                     'input': {'command': 'ls'}}]}}, **kw))


def typed(n, text, **kw):
    return ev(n, dict({'type': 'user', 'message': {'role': 'user', 'content': text}}, **kw))


def tool_result(n, **kw):
    return ev(n, dict({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}, **kw))


def noise(n):
    """The events a waiting session gathers with no message in them: a Claude app or the Kit connects, and
    Claude Code starts again."""
    kinds = ({'type': 'system', 'subtype': 'init'}, {'type': 'system', 'subtype': 'status'},
             {'type': 'control_request', 'request': {'subtype': 'initialize'}}, {'type': 'control_response'},
             {'type': 'rate_limit_event'}, {'type': 'control_request', 'request': {'subtype': 'apply_flag_settings'}})
    return ev(n, kinds[n % len(kinds)], 'client' if n % 3 == 2 else 'worker')


TABLE = ('The ink supplier asked if you want the new cyan sample run next week.\n\n'
         '| Ask | Status | Need from you |\n|---|---|---|\n'
         '| Cyan sample run | 🔴 | Pick a day |\n| Laminate quote | 🔄 | Nothing |')
TABLE_PLAIN = ('The ink supplier asked if you want the new cyan sample run next week.\n\n'
               'Cyan sample run\n  Needs you: Pick a day\n\nLaminate quote\n  In progress')


class Reply(unittest.TestCase):
    """last_reply is all the text of the newest turn that has text, the session's own (events newest first)."""

    def test_text_before_and_after_tool_steps_is_one_reply(self):
        evs = [ev(9, {'type': 'result', 'subtype': 'success'}), said(8, 'Done: press 3 runs.'), tool_result(7),
               tool(6), said(5, 'I check the **press 3** queue.'), typed(4, 'Is press 3 free?'),
               ev(3, {'type': 'result'}), said(2, 'An older reply.'), typed(1, 'Hello')]
        self.assertEqual(detail.last_reply(evs), 'I check the press 3 queue.\n\nDone: press 3 runs.')

    def test_last_message_only_tool_steps(self):
        evs = [tool_result(5), tool(4), said(3, 'I send the note to the second shift now.'), typed(2, 'Send it')]
        self.assertEqual(detail.last_reply(evs), 'I send the note to the second shift now.')

    def test_new_turn_with_no_text_yet_keeps_the_last_reply(self):
        evs = [tool(6), typed(5, '[Sttark Claude Kit] A wait you handed to the Kit has ended.', origin={'kind': 'human'}),
               ev(4, {'type': 'result'}), said(3, TABLE), tool(2), typed(1, 'What do the suppliers need?')]
        self.assertEqual(detail.last_reply(evs), TABLE_PLAIN)

    def test_an_agents_text_is_not_the_reply(self):
        evs = [said(7, 'Agent: the rewinder manual is on page 4.', parent_tool_use_id='tu_agent',
                    subagent_type='general-purpose'),
               tool_result(6, parent_tool_use_id='tu_agent'), tool(5, parent_tool_use_id='tu_agent'),
               typed(4, 'Find the rewinder manual.', parent_tool_use_id='tu_agent'),
               ev(3, {'type': 'result'}), said(2, 'An agent looks for the rewinder manual.'), typed(1, 'Rewinder 2?')]
        self.assertEqual(detail.last_reply(evs), 'An agent looks for the rewinder manual.')

    def test_only_a_typed_message_starts_a_turn(self):
        notice = {'kind': 'task-notification', 'producer': 'session-task'}
        evs = [said(8, 'The agent found it.'), typed(7, '<task-notification>done</task-notification>', origin=notice),
               typed(6, '[Image: source: /tmp/press.png]', isSynthetic=True), said(5, 'I start an agent.'),
               typed(4, 'Find the press 5 manual.', client_platform='ios'), said(3, 'Older.'), typed(2, 'Hi')]
        self.assertEqual(detail.last_reply(evs), 'I start an agent.\n\nThe agent found it.')
        self.assertTrue(detail.reply_whole(evs))
        self.assertEqual(detail.reply_start(evs), 5)

    def test_not_whole_without_the_turn_start(self):
        self.assertFalse(detail.reply_whole([said(3, 'Part two.'), tool(2), said(1, 'Part one.')]))
        self.assertFalse(detail.reply_whole([noise(n) for n in range(100, 0, -1)]))

    def test_slim_keeps_only_what_the_reply_needs(self):
        e = ev(5, {'type': 'assistant', 'uuid': 'u1', 'message': {'id': 'm1', 'content': [
            {'type': 'text', 'text': 'Done.'}, {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'x' * 5000}}]}})
        self.assertEqual(detail.slim(e), {'sequence_num': '5', 'payload': {'type': 'assistant', 'message': {
            'content': [{'type': 'text', 'text': 'Done.'}, {'type': 'tool_use'}]}}})
        self.assertEqual(detail.last_reply([detail.slim(e)]), 'Done.')


class OlderEvents(unittest.TestCase):
    """A waiting session's reply below the newest 100 events: the bridge reads further back, once."""

    def setUp(self):
        import bridge
        self.bridge = bridge
        # the made-up session: a turn with the reply (1-6), then 150 events with no message in them (7-156)
        self.history = [typed(1, 'What do the suppliers need?'), tool(2), tool_result(3), said(4, TABLE),
                        ev(5, {'type': 'result', 'subtype': 'success'}), noise(6)] + [noise(n) for n in range(7, 157)]
        self.calls = []

        def events(cse, limit=100, desc=True, cursor=None):
            self.calls.append((limit, cursor))
            if limit > 500:
                raise bridge.rcapi.APIError(400, 'limit too large')
            newest = sorted(self.history, key=detail.seq, reverse=True)
            below = [e for e in newest if cursor is None or detail.seq(e) < int(cursor)]
            page = below[:limit]
            return page, (detail.seq(page[-1]) if len(below) > limit else None)

        self._events, self._log = bridge.rcapi.events, bridge.log
        bridge.rcapi.events, bridge.log = events, lambda msg: None
        hub = bridge.Hub.__new__(bridge.Hub)
        hub.lock, hub.older = threading.RLock(), {}
        self.hub = hub

    def tearDown(self):
        self.bridge.rcapi.events, self.bridge.log = self._events, self._log

    def newest(self, n=100):
        return sorted(self.history, key=detail.seq, reverse=True)[:n]

    def test_reply_found_below_the_newest_page_and_kept(self):
        window = self.newest()
        self.assertEqual(detail.last_reply(window), '')  # what the bridge showed: "No reply yet."
        evs = self.hub.reply_events('cse_x', window)
        self.assertEqual(detail.last_reply(evs), TABLE_PLAIN)
        self.assertEqual(self.calls, [(500, 57)])  # one read: the events before the window's oldest
        # the next read (a new event came) uses the kept events: no call
        self.history.append(noise(157))
        self.calls.clear()
        self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())), TABLE_PLAIN)
        self.assertEqual(self.calls, [])
        kept = [detail.seq(e) for e in self.hub.older['cse_x']['events']]
        self.assertEqual((kept[0], kept[-1], len(kept)), (157, 1, 157))  # from the newest down to the turn start

    def test_a_new_reply_on_top_needs_no_read(self):
        self.hub.reply_events('cse_x', self.newest())
        self.history += [typed(157, 'And the laminate?'), said(158, 'The laminate quote comes Friday.'),
                         ev(159, {'type': 'result'})]
        self.calls.clear()
        self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())),
                         'The laminate quote comes Friday.')
        self.assertEqual(self.calls, [])

    def test_a_gap_reads_again(self):
        self.hub.reply_events('cse_x', self.newest())
        self.history += [noise(n) for n in range(157, 400)]  # more than a page came since the last read
        self.calls.clear()
        self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())), TABLE_PLAIN)
        self.assertEqual(self.calls, [(500, 300)])

    def test_session_with_no_text_reads_to_its_start_once(self):
        self.history = [typed(1, 'Run the nozzle check.'), tool(2)] + [noise(n) for n in range(3, 160)]
        self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())), '')
        self.assertEqual(len(self.calls), 1)
        self.calls.clear()
        self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())), '')
        self.assertEqual(self.calls, [])

    def test_smaller_pages_when_the_api_refuses_big_ones(self):
        self.bridge.OLDER_PAGE, old = 1000, self.bridge.OLDER_PAGE
        try:
            self.assertEqual(detail.last_reply(self.hub.reply_events('cse_x', self.newest())), TABLE_PLAIN)
        finally:
            self.bridge.OLDER_PAGE = old
        self.assertEqual(self.calls, [(1000, 57), (100, 57)])


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


def asked(n, text, source='client', at=None, **extra):
    p = dict({'type': 'user', 'message': {'role': 'user', 'content': text}}, **extra)
    if at:
        p['timestamp'] = at
    return ev(n, p, source)


def wrote(n, *blocks, **extra):
    content = [{'type': 'text', 'text': b} if isinstance(b, str) else b for b in blocks]
    return ev(n, dict({'type': 'assistant', 'message': {'role': 'assistant', 'content': content}}, **extra))


def ended(n):
    return ev(n, {'type': 'result', 'subtype': 'success'})


TOOL = {'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {}}


class Turns(unittest.TestCase):
    """The session's history as turns: one prompt and all of Claude's text after it (made-up press and quote work)."""

    def session(self):
        return [
            asked(1, 'Check the **Press 3** nozzle report', at='2026-11-18T13:05:00Z'),
            wrote(2, {'type': 'thinking', 'thinking': ''}),
            wrote(3, 'I read the report.', TOOL),
            tool_result(4),
            ev(5, {'type': 'user', 'message': {'content': '[Image: original 2800x1880, displayed at 2000x1343.]'},
                   'isSynthetic': True}),
            wrote(6, 'Draft for the agent', parent_tool_use_id='toolu_agent'),  # an agent's own words
            wrote(7, 'Head 2 has **6** nozzles out.\n\n| Head | State |\n|---|---|\n| 2 | 6 out |'),
            ended(8),
            asked(9, '[Sttark Claude Kit] A wait you handed to the Kit has ended. New Star Labels wrote: "Quote '
                    'attached." The wait: a reply on the laminate quote.', source='worker', origin={'kind': 'human'}),
            wrote(10, 'New Star quotes $0.12 per m for 5,000 m.'),
            ended(11),
            asked(12, '<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n<summary>Agent "Price '
                     'the laminate" finished</summary>\n</task-notification>', source='worker',
                 origin={'kind': 'task-notification'}),
            wrote(13, 'The agent priced 8,000 m too: $0.11 per m.'),
            ended(14),
            asked(15, 'Order 5,000 m'),
            wrote(16, TOOL),
            asked(17, 'Wait, make it 8,000 m', priority='next'),  # sent while Claude works: that run stops
            ended(18),
            asked(19, '[Request interrupted by user]', source='worker'),
            wrote(20, 'Changed to 8,000 m. The order draft is saved.'),
            ended(21),
        ]

    def test_prompts_and_their_replies(self):
        ts = detail.turns(self.session())
        self.assertEqual([(t['index'], t['from'], t['user_text']) for t in ts], [
            (0, 'you', 'Check the Press 3 nozzle report'),
            (1, 'kit', 'A wait you handed to the Kit has ended.'),
            (2, 'task', 'Agent "Price the laminate" finished'),
            (3, 'you', 'Order 5,000 m'),
            (4, 'you', 'Wait, make it 8,000 m'),
        ])
        self.assertEqual(ts[0]['at'], '2026-11-18T13:05:00Z')
        # All of a turn's text, from each message, as plain text; not the agent's, not the tool steps.
        self.assertEqual(ts[0]['reply_text'], 'I read the report.\n\nHead 2 has 6 nozzles out.\n\n2\n  State: 6 out')
        self.assertEqual(ts[1]['reply_text'], 'New Star quotes $0.12 per m for 5,000 m.')
        self.assertEqual(ts[3]['reply_text'], '')  # it only used a tool before the next prompt
        self.assertEqual(ts[4]['reply_text'], 'Changed to 8,000 m. The order draft is saved.')
        self.assertEqual(detail.latest_turn(ts), 4)

    def test_latest_is_the_newest_turn_with_text(self):
        evs = self.session()[:14] + [asked(15, 'Order 5,000 m'), wrote(16, TOOL)]  # Claude works on it
        ts = detail.turns(evs)
        self.assertEqual(len(ts), 4)
        self.assertEqual(detail.latest_turn(ts), 2)
        self.assertEqual(detail.latest_turn([]), -1)

    def test_the_latest_turn_is_the_last_reply(self):
        """The session screen shows last_reply; the earlier turns are the ones before it, so they must agree."""
        evs = self.session()
        for n in range(1, len(evs) + 1):
            ts = detail.turns(evs[:n])
            i = detail.latest_turn(ts)
            self.assertEqual(ts[i]['reply_text'] if i >= 0 else '', detail.last_reply(evs[:n][::-1]), n)

    def test_text_after_a_finished_turn_with_no_prompt(self):
        ts = detail.turns([asked(1, 'Check Rewinder 2'), wrote(2, 'Belts are worn.'), ended(3),
                           wrote(4, 'The supplier answered: 2 belts ship Friday.')])
        self.assertEqual([(t['from'], t['user_text'], t['reply_text']) for t in ts], [
            ('you', 'Check Rewinder 2', 'Belts are worn.'),
            ('claude', '', 'The supplier answered: 2 belts ship Friday.')])

    def test_task_notice_as_a_system_event(self):
        """Before Claude Code 2.1.320 a background agent's end came as a system event, then Claude's run for it."""
        ts = detail.turns([
            asked(1, 'Merge the new die drawing'), wrote(2, 'An agent merges it now.'), ended(3),
            ev(4, {'type': 'system', 'subtype': 'task_started', 'task_id': 'a1', 'description': 'Merge the die drawing'}),
            ev(5, {'type': 'system', 'subtype': 'task_started', 'task_id': 'b1', 'description': 'Export the PDF',
                   'owned_by_subagent': True}),
            ev(6, {'type': 'system', 'subtype': 'task_notification', 'task_id': 'b1', 'summary': 'Export the PDF'}),
            ev(7, {'type': 'system', 'subtype': 'task_notification', 'task_id': 'a1', 'summary': 'I merged the die.'}),
            wrote(8, TOOL), tool_result(9), wrote(10, 'The die drawing is merged.'), ended(11),
            ev(12, {'type': 'system', 'subtype': 'task_notification', 'task_id': 'zz', 'summary': 'Rewinder 2 check '
                                                                                                  'is done. All good.'}),
            wrote(13, 'Rewinder 2 is fine.'),
        ])
        self.assertEqual([(t['from'], t['user_text'], t['reply_text']) for t in ts], [
            ('you', 'Merge the new die drawing', 'An agent merges it now.'),
            ('task', 'Agent "Merge the die drawing" finished', 'The die drawing is merged.'),
            ('task', 'Rewinder 2 check is done.', 'Rewinder 2 is fine.')])

    def test_images_and_empty_prompts(self):
        img = {'type': 'image', 'source': {'type': 'base64', 'data': 'AAAA'}}
        ts = detail.turns([
            ev(1, {'type': 'user', 'message': {'content': [img, {'type': 'text', 'text': 'Is this roll on its edge?'}]}}),
            ev(2, {'type': 'user', 'message': {'content': [img, img]}}),
            ev(3, {'type': 'user', 'message': {'content': '   '}}),
            ev(4, {'type': 'user', 'message': {'content': '<system-reminder>x</system-reminder>'}, 'isMeta': True}),
        ])
        self.assertEqual([t['user_text'] for t in ts], ['Is this roll on its edge? [image]', '[2 images]'])

    def test_slim_keeps_only_what_turns_need(self):
        e = wrote(7, 'Head 2 is out.', TOOL)
        e['created_at'] = '2026-11-18T13:06:00Z'
        s = detail.slim_event(e)
        self.assertEqual(s, {'sequence_num': '7', 'created_at': '2026-11-18T13:06:00Z', 'payload': {
            'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Head 2 is out.'}, {'type': 'tool_use'}]}}})
        self.assertEqual(detail.turns([detail.slim_event(x) for x in self.session()]), detail.turns(self.session()))


class History(unittest.TestCase):
    """The bridge reads a session's events once, in pages, then only the new ones; the endpoint gives a slice."""

    def setUp(self):
        import bridge
        import rcapi
        self.bridge, self.rcapi = bridge, rcapi
        self.events = Turns().session()
        self.calls = []

        def events(cse, limit=100, desc=True, cursor=None):
            self.calls.append((limit, desc, cursor))
            after = [e for e in self.events if detail.seq(e) > int(cursor or 0)][:limit]
            return after, (detail.seq(after[-1]) if after else None)

        self._events, rcapi.events = rcapi.events, events
        self._log, bridge.log = bridge.log, lambda msg: None  # never the Mac's real log
        bridge.History.PAGE = 5

    def tearDown(self):
        self.rcapi.events = self._events
        self.bridge.log = self._log
        self.bridge.History.PAGE = 1000

    def hub(self):
        hub = self.bridge.Hub.__new__(self.bridge.Hub)
        hub.lock, hub.trackers, hub.histories, hub.api = threading.RLock(), {}, {}, {}
        hub.session_record = lambda cse: {}
        return hub

    def test_pages_then_only_new_events(self):
        hub = self.hub()
        cse = 'cse_01AAAAAAAAAAAAAAAAAAAAAA'
        r = hub.turns(cse)
        self.assertEqual((r['total'], r['latest']), (5, 4))
        self.assertEqual([t['index'] for t in r['turns']], [0, 1, 2, 3, 4])
        self.assertEqual(self.calls, [(5, False, None), (5, False, 5), (5, False, 10), (5, False, 15), (5, False, 20)])
        r = hub.turns(cse, before=4, limit=2)
        self.assertEqual([t['index'] for t in r['turns']], [2, 3])
        self.assertEqual(len(self.calls), 5)  # read 3 s ago at most: no new call
        self.events.append(asked(22, 'Send it to New Star'))
        hub.histories[cse].read_at = 0
        r = hub.turns(cse, before=1)
        self.assertEqual(([t['index'] for t in r['turns']], r['total'], r['latest']), ([0], 6, 4))
        self.assertEqual(self.calls[-1], (5, False, 21))
        self.assertEqual(hub.turns(cse, before=0)['turns'], [])


class Live(unittest.TestCase):
    """What a glasses client's live messages do: the session it shows replaces the one before."""

    def setUp(self):
        import bridge
        self.bridge = bridge

        class FakeTracker:
            def __init__(self, hub, cse):
                self.cse, self.watchers, self.idle_since = cse, 0, None
                self.stop, self.ready = threading.Event(), threading.Event()
                self.ready.set()

        self._tracker = bridge.Tracker
        bridge.Tracker = FakeTracker
        hub = bridge.Hub.__new__(bridge.Hub)
        hub.lock, hub.trackers, hub.sent, hub.clients = threading.RLock(), {}, {}, set()
        hub.pushed = []
        hub.session_changed = lambda cse: hub.pushed.append(cse)
        self.hub = hub
        self.client = bridge.Client(None)
        self.client.sent = []
        self.client.send = self.client.sent.append

    def tearDown(self):
        self.bridge.Tracker = self._tracker

    def watchers(self):
        return {c: t.watchers for c, t in self.hub.trackers.items()}

    def test_subscribe_replaces_and_null_follows_none(self):
        a, b = 'cse_01AAAAAAAAAAAAAAAAAAAAAA', 'session_01BBBBBBBBBBBBBBBBBBBBBB'
        self.hub.live_message(self.client, {'type': 'subscribe', 'id': a})
        self.hub.live_message(self.client, {'type': 'subscribe', 'id': a})  # again: counted once
        self.assertEqual(self.client.subs, {a})
        self.assertEqual(self.watchers(), {a: 1})
        self.hub.live_message(self.client, {'type': 'subscribe', 'id': b})
        self.assertEqual(self.client.subs, {'cse_01BBBBBBBBBBBBBBBBBBBBBB'})
        self.assertEqual(self.watchers()[a], 0)
        self.hub.live_message(self.client, {'type': 'subscribe', 'id': None})
        self.assertEqual(self.client.subs, set())
        self.assertTrue(all(w == 0 for w in self.watchers().values()))
        for _ in range(50):  # the detail goes out from a thread
            if len(self.hub.pushed) >= 3:
                break
            time.sleep(0.02)
        self.assertEqual(self.hub.pushed.count(a), 2)

    def test_unsubscribe_and_ping(self):
        a = 'cse_01AAAAAAAAAAAAAAAAAAAAAA'
        self.hub.live_message(self.client, {'type': 'subscribe', 'id': a})
        self.hub.live_message(self.client, {'type': 'unsubscribe', 'id': a})
        self.assertEqual(self.client.subs, set())
        self.hub.live_message(self.client, {'type': 'ping'})
        self.assertEqual(self.client.sent, [{'type': 'pong'}])
        self.hub.live_message(self.client, ['not', 'a', 'dict'])


# -- glance cards (glance.py): made-up press jobs and supplier quotes --------------------------------------------------

QUOTE = ('Harbor Film price: $4,820 for 50,000 labels ($0.0964 each), delivered. The lead time is 2 weeks after you '
         'approve the proof. A rush order costs 15% more.\n\nTo go ahead, approve the proof in the portal.')
ASKS = ('Where the open asks stand:\n\n'
        '| Ask | Status | Need from you |\n|---|---|---|\n'
        '| Laminate quote from New Star Labels | 🔄 Waiting on New Star, Mon 11/30 | Nothing |\n'
        '| Job 4490 proof for the customer | 🔴 Needs you | Tell me a day and time for the press check. |\n'
        '| Rewinder 2 belts | ✅ Done | - |\n'
        '| Press 3 head 2 order | 🔴 | Pick 1 or 2 heads, and I make the order draft. |\n'
        '| Die quote from Harbor Dies | ⚪ Dropped | |\n\nTwo need you.')
QUESTION_VIEW = {'kind': 'question', 'text': 'Which press runs job 4471?', 'options': [
    {'id': 'q0.o0', 'label': 'Press 3 (gloss line)'}, {'id': 'q0.o1', 'label': 'Press 5 (matte line)'}],
    'request_id': 'r1'}


class FakeHaiku:
    """Stands in for Haiku: answers with a fixed text and counts the calls."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, system, text):
        self.calls.append((system, text))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class GlanceTable(unittest.TestCase):
    def test_status_table_rows(self):
        rows = glance.status_table(ASKS)
        self.assertEqual([r['state'] for r in rows], ['working', 'needs', 'done', 'needs', 'dropped'])
        self.assertEqual(rows[1]['need'], 'Tell me a day and time for the press check.')
        self.assertEqual(rows[0]['status'], 'Waiting on New Star, Mon 11/30')
        self.assertIsNone(glance.status_table(QUOTE))
        self.assertIsNone(glance.status_table('| Head | Nozzles |\n|---|---|\n| 2 | 6 out |'))  # no status column

    def test_card_from_table_needs_you_first(self):
        haiku = FakeHaiku(json.dumps({'rows': [
            {'ask': 'Laminate quote', 'what': 'wait New Star, Mon 11/30'},
            {'ask': 'Job 4490 proof', 'what': 'pick a day + time'},
            {'ask': 'Rewinder 2 belts', 'what': 'done'},
            {'ask': 'Head 2 order', 'what': 'pick 1 or 2 heads'},
            {'ask': 'Harbor die quote', 'what': 'dropped'}], 'options': []}))
        g = glance.serve(glance.make('Open asks', ASKS, None, haiku), 'idle')
        self.assertEqual(g['lines'], ['! Job 4490 proof: pick a day + time', '! Head 2 order: pick 1 or 2 heads',
                                      'Laminate quote: wait New Star, Mon 11/30', 'Rewinder 2 belts: done',
                                      'Harbor die quote: dropped'])
        self.assertEqual(g['states'], ['needs', 'needs', 'working', 'done', 'dropped'])
        self.assertEqual(g['status_word'], 'NEEDS YOU')
        self.assertIsNone(g['you'])  # the ! lines say what to do
        self.assertEqual(g['phrase'], '2 asks need you')
        self.assertIn('"Laminate quote from New Star Labels"', haiku.calls[0][1])

    def test_table_row_with_a_new_number_keeps_its_own_words(self):
        haiku = FakeHaiku(json.dumps({'rows': [{'ask': 'Laminate', 'what': 'wait, Mon 12/7'}] + [
            {'ask': 'x', 'what': 'y'}] * 4}))
        g = glance.serve(glance.make('Open asks', ASKS, None, haiku), 'idle')
        self.assertEqual(g['lines'][2], 'Laminate quote: Waiting on New Star, Mon 11/30')

    def test_table_with_nothing_for_you(self):
        md = '| Job | Status |\n|---|---|\n| Job 4471 | 🔄 On Press 3 |\n| Job 4475 | ✅ |'
        g = glance.serve(glance.short_card(md, None, glance.status_table(md)), 'idle')
        self.assertEqual(g['lines'], ['Job 4471: On Press 3', 'Job 4475: done'])
        self.assertEqual(g['you'], 'nothing now')
        self.assertEqual(g['status_word'], 'WAITING')  # a finished turn whose asks still run


class GlanceSummary(unittest.TestCase):
    def test_key_fact_first_and_numbers_kept(self):
        haiku = FakeHaiku('Here it is:\n```json\n' + json.dumps({
            'status_word': 'NEEDS YOU', 'lines': ['Harbor Film: $4,820 for 50,000', 'Lead: 2 wk after proof OK',
                                                  'Rush: +15%'], 'you': 'approve the proof', 'options': []}) + '\n```')
        g = glance.serve(glance.make('Label quote', QUOTE, None, haiku), 'idle')
        self.assertEqual(g['lines'], ['Harbor Film: $4,820 for 50,000', 'Lead: 2 wk after proof OK', 'Rush: +15%'])
        self.assertEqual((g['you'], g['status_word'], g['phrase']), ('approve the proof', 'NEEDS YOU',
                                                                      'approve the proof'))

    def test_a_line_with_a_number_not_in_the_reply_goes(self):
        haiku = FakeHaiku(json.dumps({'status_word': 'DONE', 'lines': ['Harbor Film: $4,280 for 50,000',
                                                                       'Lead: 2 wk'], 'you': 'nothing now'}))
        g = glance.serve(glance.make('Label quote', QUOTE, None, haiku), 'idle')
        self.assertEqual(g['lines'], ['Lead: 2 wk'])
        self.assertEqual(g['phrase'], 'Lead: 2 wk')

    def test_live_state_sets_the_word(self):
        card = {'from': 'summary', 'word': 'DONE', 'lines': ['Job 4471: on Press 3'], 'you': 'nothing now',
                'options': []}
        self.assertEqual(glance.serve(card, 'working')['status_word'], 'WORKING')
        self.assertEqual(glance.serve(card, 'waiting')['status_word'], 'WAITING')
        self.assertEqual(glance.serve(card, 'needs_you')['status_word'], 'NEEDS YOU')
        self.assertEqual(glance.serve(card, 'idle')['status_word'], 'DONE')

    def test_short_answers_for_the_buttons(self):
        haiku = FakeHaiku(json.dumps({'status_word': 'NEEDS YOU', 'lines': ['Job 4471: which press?'],
                                      'you': 'pick a press', 'options': ['Press 3', 'Press 5']}))
        g = glance.serve(glance.make('Job 4471', 'Job 4471 is ready to run.', QUESTION_VIEW, haiku), 'needs_you')
        self.assertEqual(g['options'], [{'id': 'q0.o0', 'label': 'Press 3'}, {'id': 'q0.o1', 'label': 'Press 5'}])
        self.assertIn('Options: 1. Press 3 (gloss line) | 2. Press 5 (matte line)', haiku.calls[0][1])
        # A list of another length: the question's own labels.
        haiku.answer = json.dumps({'status_word': 'NEEDS YOU', 'lines': ['Job 4471: which press?'], 'you': 'pick',
                                   'options': ['Press 3']})
        g = glance.serve(glance.make('Job 4471', 'Job 4471 is ready to run.', QUESTION_VIEW, haiku), 'needs_you')
        self.assertEqual([o['label'] for o in g['options']], ['Press 3 (gloss line)', 'Press 5 (matte line)'])

    def test_first_sentence_without_the_model(self):
        g = glance.serve(glance.short_card(QUOTE, None), 'idle')
        self.assertEqual(g['lines'], ['Harbor Film price: $4,820 for 50,000 labels ($0.0964 each), delivered.'])
        self.assertEqual(g['source'], 'short')
        g = glance.serve(glance.short_card(QUOTE, QUESTION_VIEW), 'needs_you')
        self.assertEqual((g['lines'], g['you']), (['Which press runs job 4471?'], 'pick below'))


class GlanceCards(unittest.TestCase):
    """The cards of every session: made once per reply, in the background, kept on disk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ready = []
        self.inputs = {'cse_quote': ('Label quote', QUOTE, None)}

    def cards(self, haiku, **kw):
        return glance.Cards(self.dir, fetch=lambda cse: self.inputs.get(cse), ready=self.ready.append, ask=haiku,
                            log=lambda *_: None, **kw)

    def wait_ready(self, n=1):
        for _ in range(200):
            if len(self.ready) >= n:
                return
            time.sleep(0.01)
        self.fail('no card was made')

    def test_once_per_reply_and_kept_on_disk(self):
        haiku = FakeHaiku(json.dumps({'status_word': 'DONE', 'lines': ['Harbor Film: $4,820'], 'you': 'nothing now'}))
        c = self.cards(haiku)
        short = c.for_reply('cse_quote', 'Label quote', QUOTE, None, 'm1')
        self.assertEqual(short['source'], 'short')  # at once: the first sentence
        self.wait_ready()
        self.assertEqual(c.for_reply('cse_quote', 'Label quote', QUOTE, None, 'm2')['lines'], ['Harbor Film: $4,820'])
        c.note('cse_quote', 'Label quote', 'm3', 2)  # the list moved on, the reply did not
        self.wait_ready(2)
        self.assertEqual(len(haiku.calls), 1)
        c.stop.set()
        again = self.cards(FakeHaiku(RuntimeError('not called')))
        self.assertEqual(again.card('cse_quote')['lines'], ['Harbor Film: $4,820'])
        self.assertEqual(oct(os.stat(os.path.join(self.dir, 'glances.json')).st_mode & 0o777), '0o600')

    def test_a_failed_call_leaves_the_first_sentence(self):
        c = self.cards(FakeHaiku(RuntimeError('exit 1')))
        c.note('cse_quote', 'Label quote', 'm1', 1)
        self.wait_ready()
        self.assertEqual(c.card('cse_quote')['source'], 'short')

    def test_held_at_the_limit_calls_nothing(self):
        haiku = FakeHaiku('{}')
        c = self.cards(haiku, held=lambda: True)
        c.note('cse_quote', 'Label quote', 'm1', 1)
        self.wait_ready()
        self.assertEqual(haiku.calls, [])

    def test_only_sessions_named_so(self):
        haiku = FakeHaiku('{}')
        c = self.cards(haiku, only='G2')
        c.note('cse_quote', 'Label quote', 'm1', 1)
        time.sleep(0.1)
        self.assertEqual((haiku.calls, self.ready), ([], []))


if __name__ == '__main__':
    unittest.main()


class Title(unittest.TestCase):
    def test_first_line_cut_at_a_word(self):
        import bridge
        self.assertEqual(bridge.title_of('Rewinder 2 belts\nOrder two from the usual supplier.'), 'Rewinder 2 belts')
        t = bridge.title_of('Write a short note to the second shift about the Press 3 heads and the purge times.')
        self.assertEqual(t, 'Write a short note to the second shift about the Press 3...')
        self.assertLessEqual(len(t), 61)
        self.assertEqual(bridge.title_of('   '), 'New session')
