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
      // A reply that ended in a 3-column status table (Ask | Status | Need
      // from you, a status emoji in each row). The bridge sends each table
      // row as a card (glasses/bridge/detail.py) in last_reply, and the
      // table's cells in reply_parts, for the lens to draw as a picture.
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
      reply_parts: [
        { text: 'Where the open asks stand:' },
        {
          table: {
            heads: ['Ask', 'Status', 'Need from you'],
            rows: [
              ['Laminate quote from New Star Labels', 'Needs you', 'Pick 5,000 m or 8,000 m, and I make the order draft.'],
              ['Press 3 head 2 order', 'In progress', 'Nothing'],
              ['Rewinder 2 belts', 'Done', 'Nothing'],
              ['Job 4490 proof for the customer', 'Needs you', 'Tell me a day and time for the press check, and I make a reply draft.'],
              ['Die quote from Harbor Dies', 'Dropped', 'Nothing'],
            ],
          },
        },
        { text: 'Two need you: the laminate and the press check.' },
      ],
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
      last_reply:
        'Two of the three suppliers sent a price for the two drive belts for Rewinder 2.\n\n' +
        'Belt Supply Co.\n  Belt: HTD 8M-1200-30\n  Price: $38.50 each\n  Ships: 2 days\n  Notes: Same belt as the one on the machine, from stock\n\n' +
        'Harbor Power Transmission\n  Belt: HTD 8M-1200-30\n  Price: $31.20 each\n  Ships: 3 weeks\n  Notes: Made to order, minimum of 4 belts, so the order is $124.80\n\n' +
        'Midway Bearing\n  Price: No answer yet\n\n' +
        'I will check the inbox again at 2:00 PM for the third price.',
      reply_parts: [
        { text: 'Two of the three suppliers sent a price for the two drive belts for Rewinder 2.' },
        {
          table: {
            heads: ['Supplier', 'Belt', 'Price', 'Ships', 'Notes'],
            rows: [
              ['Belt Supply Co.', 'HTD 8M-1200-30', '$38.50 each', '2 days', 'Same belt as the one on the machine, from stock'],
              ['Harbor Power Transmission', 'HTD 8M-1200-30', '$31.20 each', '3 weeks', 'Made to order, minimum of 4 belts, so the order is $124.80'],
              ['Midway Bearing', '', 'No answer yet', '', ''],
            ],
          },
        },
        { text: 'I will check the inbox again at 2:00 PM for the third price.' },
      ],
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
      last_reply:
        'The 3 x 2 in die template with 0.125 in corners is saved in the shared drive. All seven die templates there now:\n\n' +
        'D-101\n  Size: 3 x 2 in\n  Corners: 0.125 in\n  Across: 4\n  Used for: Wine labels, gloss\n\nD-102\n  Size: 4 x 6 in\n  Corners: 0.25 in\n  Across: 2\n  Used for: Shipping labels\n\nD-103\n  Size: 2 in circle\n  Corners: -\n  Across: 6\n  Used for: Jar lids\n\nD-104\n  Size: 1.5 x 1 in\n  Corners: 0.0625 in\n  Across: 8\n  Used for: Price tags\n\nD-105\n  Size: 5 x 3.5 in\n  Corners: 0.125 in\n  Across: 3\n  Used for: Coffee bags, matte\n\nD-106\n  Size: 2.5 x 4 in oval\n  Corners: -\n  Across: 4\n  Used for: Candle jars\n\nD-107\n  Size: 3 x 3 in\n  Corners: 0.1875 in\n  Across: 4\n  Used for: Sample run, Job 4462',
      reply_parts: [
        { text: 'The 3 x 2 in die template with 0.125 in corners is saved in the shared drive. All seven die templates there now:' },
        {
          table: {
            heads: ['Die', 'Size', 'Corners', 'Across', 'Used for'],
            rows: [
              ["D-101", "3 x 2 in", "0.125 in", "4", "Wine labels, gloss"],
              ["D-102", "4 x 6 in", "0.25 in", "2", "Shipping labels"],
              ["D-103", "2 in circle", "-", "6", "Jar lids"],
              ["D-104", "1.5 x 1 in", "0.0625 in", "8", "Price tags"],
              ["D-105", "5 x 3.5 in", "0.125 in", "3", "Coffee bags, matte"],
              ["D-106", "2.5 x 4 in oval", "-", "4", "Candle jars"],
              ["D-107", "3 x 3 in", "0.1875 in", "4", "Sample run, Job 4462"],
            ],
          },
        },
      ],
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
