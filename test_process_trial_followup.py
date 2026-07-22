import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import process_trial_followup


class ProcessTrialFollowupTests(unittest.TestCase):
    def test_new_campaign_sends_initial_followup_email_when_due(self):
        candidate = {
            "learner_id": "learner-1",
            "parent_id": "parent-1",
            "free_trial_pass_id": "trial-1",
            "trial_expiry_at": datetime.now(timezone.utc) - timedelta(days=2),
            "learner_name": "Test Learner",
        }

        with patch.object(process_trial_followup, "get_trial_followup_candidates", return_value=[candidate]), \
             patch.object(process_trial_followup, "get_followup_history", return_value={}), \
             patch.object(process_trial_followup, "create_followup") as mock_create, \
             patch.object(process_trial_followup, "send_followup_email", return_value=True) as mock_send:
            process_trial_followup.process_trial_followups()

        mock_create.assert_called_once()
        mock_send.assert_called_once_with(candidate, "parent-1", "learner-1", 1)


if __name__ == "__main__":
    unittest.main()
