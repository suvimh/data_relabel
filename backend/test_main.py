import os
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labelling_core as core
import main as api


class LabellingApiTests(unittest.TestCase):
    def test_session_status_does_not_return_source_filenames_or_paths(self):
        private_path = "/private/audio/breathy/original_recording.wav"
        saved_session = {
            "audio_files": [private_path],
            "data_dir": "/private/audio/breathy",
            "window_size": 1.0,
            "hop_size": 0.5,
        }
        with patch.object(core, "load_session_state", return_value=saved_session):
            response = api.get_status()

        self.assertTrue(response["has_session"])
        self.assertEqual(response["session"], {"window_size": 1.0, "hop_size": 0.5})
        self.assertNotIn("breathy", str(response).lower())
        self.assertNotIn(private_path, str(response))

    def test_present_technique_requires_confidence(self):
        annotations = {
            label: api.LabelAnnotation(state=0)
            for label in core.LABELS
        }
        annotations["vibrato"] = api.LabelAnnotation(state=1)
        active_session = {"audio_data": object(), "labels": core.LABELS}

        with patch.object(api, "session", active_session):
            with self.assertRaises(HTTPException) as error:
                api.confirm_segment(api.ConfirmRequest(annotations=annotations))

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("confidence", error.exception.detail.lower())

    def test_absent_or_uncertain_techniques_reject_confidence(self):
        annotations = {
            label: api.LabelAnnotation(state=0)
            for label in core.LABELS
        }
        annotations["breathy"] = api.LabelAnnotation(state=0, confidence=1)
        active_session = {"audio_data": object(), "labels": core.LABELS}

        with patch.object(api, "session", active_session):
            with self.assertRaises(HTTPException) as error:
                api.confirm_segment(api.ConfirmRequest(annotations=annotations))

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("only used for present", error.exception.detail.lower())

    def test_per_label_uncertain_state_is_not_supported(self):
        with self.assertRaises(ValueError):
            api.LabelAnnotation(state=-1)


if __name__ == "__main__":
    unittest.main()
