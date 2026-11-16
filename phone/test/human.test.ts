// The human work estimate's words (view/human.ts). The Mac window's tests
// assert the same examples, so the two always say the same thing.
import { describe, it, expect } from 'vitest';
import { humanNote, num, peopleWords, personWords, weekdays } from '../src/view/human.ts';

describe('human work in words', () => {
  it('one number: one decimal under 10 unless whole, then whole with a thousands comma', () => {
    expect(num(3)).toBe('3');
    expect(num(2.5)).toBe('2.5');
    expect(num(2.45)).toBe('2.5');
    expect(num(9.96)).toBe('10');
    expect(num(20.235)).toBe('20');
    expect(num(182.4)).toBe('182');
    expect(num(1240)).toBe('1,240');
  });

  it('one person, in the unit that fits the size', () => {
    expect(personWords(0.25)).toBe('1 person for 15 minutes');
    expect(personWords(0.004)).toBe('1 person for 1 minute');
    expect(personWords(0.995)).toBe('1 person for 1 hour');
    expect(personWords(6)).toBe('1 person for 6 hours');
    expect(personWords(7.5)).toBe('1 person for 7.5 hours');
    expect(personWords(8)).toBe('1 person for 1 day');
    expect(personWords(20)).toBe('1 person for 2.5 days');
    expect(personWords(79)).toBe('1 person for 9.9 days');
    expect(personWords(80)).toBe('1 person for 2 weeks');
    expect(personWords(519)).toBe('1 person for 13 weeks');
    expect(personWords(520)).toBe('1 person for 3 months');
    expect(personWords(809.4)).toBe('1 person for 4.7 months');
    expect(personWords(4160)).toBe('1 person for 2 years');
    expect(personWords(10000)).toBe('1 person for 4.8 years');
  });

  it('people together, over the weekdays of the period', () => {
    expect(peopleWords(809.4, '2026-11-10', '2026-11-16', '7d')).toBe('≈ 20 people full time over these 7 days');
    // A Sunday: no weekday, so it counts as 1 day.
    expect(peopleWords(3, '2026-11-15', '2026-11-15', 'today')).toBe('less than 1 person full time today');
    expect(peopleWords(12, '2026-11-16', '2026-11-16', 'today')).toBe('≈ 1.5 people full time today');
    expect(peopleWords(8, '2026-11-16', '2026-11-16', 'today')).toBe('≈ 1 person full time today');
    expect(peopleWords(100, '2026-11-02', '2026-11-09', '2026-11-02..2026-11-09')).toBe('≈ 2.1 people full time from Nov 2 to Nov 9');
    expect(peopleWords(9, '2026-11-04', '2026-11-04', '2026-11-04..2026-11-04')).toBe('≈ 1.1 people full time on Wed, Nov 4');
    // Under 1 before it is rounded: 0.95 is not "≈ 1 person".
    expect(peopleWords(160, '2026-10-18', '2026-11-16', '30d')).toBe('less than 1 person full time over these 30 days');
    expect(peopleWords(400, '2026-10-18', '2026-11-16', '30d')).toBe('≈ 2.4 people full time over these 30 days');
    expect(weekdays('2026-10-18', '2026-11-16')).toBe(21);
    expect(weekdays('2026-11-02', '2026-11-09')).toBe(6);
    expect(weekdays('2026-11-14', '2026-11-15')).toBe(1);
  });

  it('the note takes its numbers from the factors the Mac sent', () => {
    const note = humanNote([
      { name: 'Software', x: 12 },
      { name: 'Design', x: 5 },
      { name: 'Browser and admin', x: 2.5 },
      { name: 'Small or mixed', x: 2 },
    ]);
    expect(note).toBe(
      'An estimate. The Kit counts the hours Claude was at work, its agents too: the model writing and the tools it ran. ' +
        'Waits do not count: for you, at the usage limit, for checks and timers. ' +
        'Each hour counts as the hours a person needs for that kind of work: software 12, design 5, browser and admin 2.5, small or mixed 2. ' +
        'Full time is 8 hours a day, 5 days a week.',
    );
    expect(humanNote([{ name: 'Software', x: 12 }])).toContain('that kind of work: software 12. Full time');
    expect(humanNote([{ name: 'Software', x: 12 }, { name: 'Design', x: 5 }])).toContain(': software 12, design 5. ');
    expect(humanNote(undefined)).toContain('that kind of work. Full time is 8 hours');
  });
});
