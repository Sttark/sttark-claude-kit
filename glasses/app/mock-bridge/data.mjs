// Made-up sessions for the mock bridge: normal label-plant work, no real
// sessions, people or places. Fresh copies on every reset.

const min = (n) => new Date(Date.now() - n * 60000).toISOString();

// Earlier turns of two sessions, oldest first, for scrolling back: each is
// a prompt (the person's, a message the Kit typed, or a background task's
// notice) and Claude's reply to it. The latest turn is the session's own
// prompt and last_reply.
const PRESS3_EARLIER = [
  {
    at: min(190),
    from: 'you',
    user_text: "Pull this morning's start-up checks for all presses.",
    reply_text: 'Presses 1, 2 and 5 passed the 6:00 start-up check. Press 3 failed the nozzle check on heads 2 and 4. Press 4 is down for the planned roller change until noon.',
  },
  {
    at: min(175),
    from: 'you',
    user_text: 'Run a purge on Press 3 and check again.',
    reply_text: 'The purge ran at 6:30. Head 4 is better: 4 nozzles out, down from 11. Head 2 did not change: 6 nozzles out in the cyan row. Both nozzle check pages are in the Press 3 log.',
  },
  {
    at: min(120),
    from: 'kit',
    user_text: 'A wait you handed to the Kit has ended.',
    reply_text: 'The second shift lead answered: job 4471 can move to Press 5 if Press 3 is not ready by 10:00. Press 5 has the same gloss varnish loaded.',
  },
  {
    at: min(90),
    from: 'you',
    user_text: 'Is the head 2 problem new?',
    reply_text:
      'No. Head 2 has lost nozzles slowly since September:\n\n' +
      '- Sep 12: 2 nozzles out, a purge cleared them\n' +
      '- Oct 3: 3 out, a hand wipe cleared them\n' +
      '- Oct 28: 4 out, 1 came back after a purge\n' +
      '- Today: 6 out, none came back\n\n' +
      'Each time, fewer came back. That is what a head near the end of its life does: the nozzles stop one by one, and a purge no longer helps.\n\n' +
      'The head went in 14 months ago. The supplier rates these heads at 12 to 18 months on our ink.\n\n' +
      'The spare-parts list shows one head in stock, in bin N-A3-07. A head change takes about 2 hours, with the alignment print.',
  },
  {
    at: min(60),
    from: 'task',
    user_text: 'Agent "Price a new print head" finished',
    reply_text: 'A new print head costs $1,840 from the usual supplier, 5 days to ship. A second supplier has it for $1,690, 3 weeks to ship.',
  },
  {
    at: min(20),
    from: 'you',
    user_text: 'Which jobs need a lot of cyan this week?',
    reply_text: 'Three jobs this week use a lot of cyan:\n\n- Job 4471 gloss wine labels, today\n- Job 4483 coffee bags, Thursday\n- Job 4490 proof, Friday\n\nJob 4471 is the only one on Press 3.',
  },
];

const NEWSTAR_EARLIER = [
  {
    at: min(6 * 1440 + 200),
    from: 'you',
    user_text: 'Ask New Star Labels and Harbor Film for a laminate quote: 5,000 m of 330 mm matte.',
    reply_text: 'I sent both quote requests from the engineering inbox. Each asks for the price per meter, the lead time, and the ship cost to the Engineering Office.',
  },
  {
    at: min(5 * 1440 + 90),
    from: 'task',
    user_text: 'Agent "Read the supplier replies" finished',
    reply_text: 'Harbor Film Co. answered: $0.10 per m, matte only, 6 weeks to ship. New Star Labels has not answered yet.',
  },
  {
    at: min(2 * 1440 + 30),
    from: 'kit',
    user_text: 'A wait you handed to the Kit has ended.',
    reply_text: 'The deadline came, and New Star Labels did not answer the quote request. I can write a short follow-up.',
  },
];

export function sampleSessions() {
  return [
    {
      id: 'mock-press3',
      title: 'Press 3 nozzle report',
      folder: 'src',
      status: 'needs_you',
      why: 'Asked which fix to try next',
      status_line: 'Asked which fix to try next',
      updated_at: min(4),
      earlier: PRESS3_EARLIER,
      prompt: { at: min(6), from: 'you', user_text: 'Look at the nozzle check again and tell me what to do.' },
      last_reply:
        "I read the Press 3 nozzle check from this morning's start-up.\n\n" +
        '**Heads 2 and 4** still show missing nozzles after one purge:\n' +
        '- Head 2: 6 nozzles out, all in the cyan row\n' +
        '- Head 4: 4 nozzles out, black row, near the plate edge\n' +
        '- Heads 1 and 3: clean\n\n' +
        'The pattern on head 4 looks like dried ink at the plate, not a failed nozzle: the gaps sit together at one edge and moved a little between the 6:00 and 6:40 checks. ' +
        'Head 2 is different. Its gaps are spread out and did not move, which is what a head near the end of its life looks like.\n\n' +
        'Job 4471 (the gloss wine labels, 12,000 pieces) is next on Press 3. Its art uses a lot of cyan, so the head 2 gaps would show as light lines across the background.\n\n' +
        'What the maintenance log says: the last head 2 change was 14 months ago, and the spare-parts list shows one head in stock (bin N-A3-07).\n\n' +
        'I can run a second purge now, write the steps to wipe the plate by hand, or start the order for a new head. Which one?',
      pending: {
        kind: 'question',
        text: 'Heads 2 and 4 still show missing nozzles after one purge. What next?',
        options: [
          { id: 'purge', label: 'Run a second purge' },
          { id: 'wipe', label: 'Wipe the plate by hand' },
          { id: 'order', label: 'Order a new head 2' },
        ],
      },
    },
    {
      id: 'mock-newstar',
      title: 'Quote follow-up New Star',
      folder: 'src',
      status: 'needs_you',
      why: 'Wants to save an email draft',
      status_line: 'Wants to save an email draft',
      updated_at: min(11),
      earlier: NEWSTAR_EARLIER,
      prompt: { at: min(13), from: 'you', user_text: 'Yes, write the follow-up to New Star.' },
      last_reply:
        'New Star Labels has not answered the laminate quote from last Tuesday. I wrote a short follow-up that asks for the price on 5,000 m of matte laminate and the lead time to the Engineering Office.\n\n' +
        'Draft: "Hello, a quick check on our quote for 5,000 m of 330 mm matte laminate. Can you send the price and the ship date? Thanks."',
      pending: {
        kind: 'permission',
        text: 'Save this follow-up as a Gmail draft to sales@newstar.example?',
        options: [
          { id: 'allow', label: 'Allow' },
          { id: 'deny', label: 'Deny' },
        ],
      },
    },
    {
      // A reply that ended in a 3-column status table (Ask | Status | Need
      // from you, a status emoji in each row). The bridge sends each table
      // row as a card (glasses/bridge/detail.py); this is its text for it.
      id: 'mock-asks',
      title: "Today's open asks",
      folder: 'src',
      status: 'needs_you',
      why: 'Two asks need you',
      status_line: 'Two asks need you',
      updated_at: min(7),
      last_reply:
        'Where the open asks stand:\n\n' +
        'Laminate quote from New Star Labels\n  Needs you: Pick 5,000 m or 8,000 m, and I make the order draft.\n\n' +
        'Press 3 head 2 order\n  In progress\n\n' +
        'Rewinder 2 belts\n  Done\n\n' +
        'Job 4490 proof for the customer\n  Needs you: Tell me a day and time for the press check, and I make a reply draft.\n\n' +
        'Die quote from Harbor Dies\n  Dropped\n\n' +
        'Two need you: the laminate and the press check.',
      pending: null,
    },
    {
      id: 'mock-hvac',
      title: 'Docs: HVAC chapter',
      folder: 'sttark-docs',
      status: 'working',
      why: 'Writing the unit locations section',
      status_line: 'Writing the unit locations section',
      updated_at: min(1),
      last_reply: 'I am adding the unit locations to the HVAC chapter: one table per building, with the space each unit serves.',
      pending: null,
    },
    {
      id: 'mock-rewinder',
      title: 'Rewinder 2 belt order',
      folder: 'src',
      status: 'waiting',
      why: 'Waiting on the supplier price',
      status_line: 'Waiting on the supplier price',
      updated_at: min(48),
      last_reply: 'I asked the supplier for the price and ship date of two drive belts for Rewinder 2. I will check the inbox again at 2:00 PM.',
      pending: null,
    },
    {
      id: 'mock-atlas',
      title: 'Atlas web tension check',
      folder: 'src',
      status: 'working',
      why: 'Reading the tension log',
      status_line: 'Reading the tension log',
      updated_at: min(2),
      last_reply: 'Reading the last 7 days of web tension data from Atlas.',
      pending: null,
    },
    {
      id: 'mock-floorplan',
      title: 'South D rack layout',
      folder: 'src',
      status: 'needs_you',
      why: 'Plan ready to approve',
      status_line: 'Plan ready to approve',
      updated_at: min(25),
      last_reply: 'The plan is ready.',
      pending: {
        kind: 'plan',
        text:
          '## Plan: South D rack layout\n\n1. Move the two pallet racks 600 mm toward the north wall, so the aisle is 3.2 m.\n2. Keep the tile fan clear: no rack under the 24 ft grid square it hangs from.\n3. Put the roll racks along the east wall, rolls on edge.\n4. Update the floor drawing and the equipment list.',
        options: [
          { id: 'approve', label: 'Approve the plan' },
          { id: 'keep', label: 'Keep planning' },
        ],
      },
    },
    {
      id: 'mock-die',
      title: 'Label die template',
      folder: 'src',
      status: 'idle',
      why: '',
      status_line: 'Done',
      updated_at: min(180),
      last_reply: 'The 3 x 2 in die template with 0.125 in corners is saved in the shared drive.',
      pending: null,
    },
  ];
}

// The glance pictures (scripts/glance-shots.mjs, MOCK_SET=glance): replies
// like the ones that were hard to read on the lens. Made up: no real quote,
// job or person.
export function glanceSessions() {
  return [
    {
      id: 'mock-film-quote',
      title: 'Harbor Film quote',
      folder: 'src',
      status: 'needs_you',
      why: 'Wants a go on the quote',
      status_line: 'Wants a go on the quote',
      updated_at: min(6),
      last_reply:
        'Harbor Film price: $4,820 for 10 rolls ($482 each), delivered. The lead time is 3 weeks after you sign and pay the 50% deposit. ' +
        'Payment by credit card costs 3% more. For comparison, the 2023 order cost about $410 for each roll, so the price for each roll is up about 18%.\n\n' +
        'The quote is good for 30 days. To go ahead, sign the quote and pay the 50% deposit ($2,410). I can write the reply to Harbor Film when you say go.',
      pending: null,
    },
    {
      id: 'mock-feeder',
      title: 'Laminator feeder',
      folder: 'src',
      status: 'working',
      why: '1 agent working · adds the feeder to the LX-210 model',
      status_line: 'feeder CAD downloaded; agent adding it to the LX-210 model',
      updated_at: min(1),
      last_reply:
        'Where the feeder work stands:\n\n' +
        '1. Download the feeder CAD from the supplier\n  Status: Done: the STEP file is in the LX-210 folder\n\n' +
        '2. Add the feeder to the LX-210 laminator model and check it\n  Status: In progress: the agent adds and checks the feeder\n\n' +
        '3. Send the fit check to the shift lead\n  Status: Not yet: after step 2\n\n' +
        'Nothing needs you now. I tell you when the fit check is ready.',
      pending: null,
    },
    {
      id: 'mock-die-error',
      title: 'Press 5 die change',
      folder: 'src',
      status: 'needs_you',
      why: 'The job ticket did not save',
      status_line: 'The job ticket did not save',
      updated_at: min(9),
      last_reply:
        'What I did: I opened job 4471 in the press queue, set the new die (3 x 2 in, 0.125 in corners) and saved the job ticket.\n\n' +
        'Error: the save failed. The queue says "Job 4471 is locked by another user". The ticket still shows the old die.\n\n' +
        'What I need from you: close job 4471 on the Press 3 PC (it is open there since 6:40 AM), then tell me, and I save it again.',
      pending: null,
    },
    ...sampleSessions().filter((s) => s.id === 'mock-press3' || s.id === 'mock-asks'),
  ];
}

export const FOLDERS = [
  { path: '/Users/sample/src', label: 'src' },
  { path: '/Users/sample/src/sttark-docs', label: 'sttark-docs' },
  { path: '/Users/sample/src/building', label: 'building' },
];

// What the mock "hears": each dictation gets the next of these, a few words
// at a time while it grows, as a real transcription would.
export const SPOKEN = [
  'Run the second purge, then check head 2 again before job 4471.',
  'Write a short note to the second shift about the Press 3 heads.',
  'Check the Rewinder 2 belt price and order two if it is under 80 dollars.',
];
