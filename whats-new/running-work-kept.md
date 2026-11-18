# The Kit keeps the work of your agents

**Icon:** gearshape.2

**Kind:** Better

The Kit now waits for a session's agents before it brings the session back, and tells the session what stopped.

- A wait or a reply brings a session back when its agents and commands stop, at most 2 hours later.
- When the Kit must stop the work, the session gets a list at its next prompt, so it can continue.
- To see each wait and stop, open **Events** and set **Kind** to **Sessions started again**.

![Three rows on the Events page. Slitter blade change is not brought back yet, because its agents still run. Press 2 job board shows work that stopped when the server took the session over: one agent and one background command, and the session gets a list at its next prompt. A row under it says the session was told.](running-work-kept.png)
