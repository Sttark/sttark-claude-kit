# Wait for mail to a shared mailbox

**Icon:** envelope.badge

**Kind:** New

A session can wait for mail to a shared mailbox, and the Kit reads that mailbox with no model.

- To start, the session runs `claude-mail sign-in <address>` one time on each Mac and gives you a link.
- Open the link on that Mac, select the shared mailbox and click **Allow**.
- Then `claude-wait email-reply --mailbox <address>` brings the session back when new mail comes.

![Four steps. The session signs in to the shared mailbox one time on each Mac. It sets a wait on that mailbox. The Kit reads the mailbox every 5 minutes with no model. When new mail comes, the session comes back.](shared-mailbox-waits.png)
