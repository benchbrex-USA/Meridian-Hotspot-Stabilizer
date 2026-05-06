import tempfile
import unittest
from pathlib import Path

from meridian_stabilizer.notifier import drain_notifications, notification_queue_path, queue_notification, queued_notification_count


class NotifierTests(unittest.TestCase):
    def test_queue_and_drain_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            queue_notification("Title", "Message", state_dir=state_dir)
            self.assertEqual(queued_notification_count(state_dir), 1)

            delivered = drain_notifications(state_dir=state_dir, sender=lambda title, message: (True, None))

            self.assertEqual(len(delivered), 1)
            self.assertTrue(delivered[0].delivered)
            self.assertFalse(notification_queue_path(state_dir).exists())

    def test_failed_drain_keeps_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            queue_notification("Title", "Message", state_dir=state_dir)

            delivered = drain_notifications(state_dir=state_dir, sender=lambda title, message: (False, "blocked"))

            self.assertEqual(len(delivered), 1)
            self.assertFalse(delivered[0].delivered)
            self.assertEqual(queued_notification_count(state_dir), 1)


if __name__ == "__main__":
    unittest.main()
