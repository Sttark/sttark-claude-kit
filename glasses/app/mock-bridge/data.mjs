// Made-up sessions for the mock bridge: normal label-plant work, no real
// sessions, people or places. Fresh copies on every reset.

const min = (n) => new Date(Date.now() - n * 60000).toISOString();

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
