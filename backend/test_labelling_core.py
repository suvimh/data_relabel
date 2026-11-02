import csv
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labelling_core as core


class LabellingCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = self.temp_dir.name
        self.short_file = os.path.join(self.data_dir, "breathy_original.wav")
        self.long_file = os.path.join(self.data_dir, "vibrato_original.wav")
        for path in (self.short_file, self.long_file):
            with open(path, "wb"):
                pass

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_discards_files_without_a_complete_window_and_hides_filenames(self):
        def fake_load(path):
            length = 5 if path == self.short_file else 25
            return np.zeros(length), 10

        with (
            patch.object(core, "get_audio_files", return_value=[self.short_file, self.long_file]),
            patch.object(core, "load_audio_file", side_effect=fake_load),
        ):
            state, error = core.init_state(self.data_dir, window_size=1.0, hop_size=0.5)

        self.assertIsNone(error)
        self.assertEqual(
            state["current_recording_id"],
            state["recording_ids"][os.path.basename(self.long_file)],
        )
        self.assertNotIn("file_name", core.get_progress(state))
        self.assertNotIn("breathy", core.get_progress(state)["recording_id"].lower())
        self.assertFalse(os.path.exists(core.get_recording_key_path(self.data_dir)))

    def test_init_skips_unreadable_audio_without_exposing_filename(self):
        sf.write(self.long_file, np.zeros(25), 10)

        with (
            patch.object(core, "get_audio_files", return_value=[self.short_file, self.long_file]),
            patch.object(core.secrets.SystemRandom, "shuffle"),
        ):
            state, error = core.init_state(self.data_dir, window_size=1.0, hop_size=0.5)

        self.assertIsNone(error)
        self.assertEqual(state["unreadable_file_count"], 1)
        self.assertEqual(state["valid_audio_files"], [self.long_file])
        self.assertNotIn("breathy", core.get_progress(state)["recording_id"].lower())

    def test_all_unreadable_files_return_an_explicit_start_error(self):
        with (
            patch.object(core, "get_audio_files", return_value=[self.short_file]),
            patch.object(core, "load_audio_file", side_effect=EOFError("empty file")),
        ):
            state, error = core.init_state(self.data_dir, window_size=1.0, hop_size=0.5)

        self.assertIsNone(state["audio_data"])
        self.assertIn("1 unreadable", error)

    def test_last_partial_window_is_not_advanced_to(self):
        state = {
            "audio_files": [self.long_file],
            "recording_ids": {os.path.basename(self.long_file): "R-TEST0001"},
            "data_dir": self.data_dir,
            "current_file_idx": 0,
            "current_segment_start": 1.5,
            "segment_num": 3,
            "window_size": 1.0,
            "hop_size": 0.5,
            "audio_data": np.zeros(25),
            "sr": 10,
        }

        self.assertFalse(core.advance_segment(state))
        self.assertIsNone(state["audio_data"])

    def test_resume_preserves_current_complete_segment(self):
        state = {
            "audio_files": [self.long_file],
            "recording_ids": {os.path.basename(self.long_file): "R-TEST0001"},
            "data_dir": self.data_dir,
            "current_file_idx": 0,
            "current_segment_start": 0.5,
            "segment_num": 1,
            "window_size": 1.0,
            "hop_size": 0.5,
            "audio_data": None,
            "sr": None,
            "labels": core.LABELS,
        }

        with patch.object(core, "load_audio_file", return_value=(np.zeros(25), 10)):
            resumed, error = core.resume_state(state)

        self.assertIsNone(error)
        self.assertEqual(resumed["current_segment_start"], 0.5)
        self.assertEqual(resumed["current_segment_end"], 1.5)

    def test_annotations_use_state_and_confidence_columns(self):
        csv_path = core.get_annotations_path(self.data_dir)
        core.init_annotations_csv(csv_path, core.LABELS)
        annotations = {
            label: {"state": 0, "confidence": None}
            for label in core.LABELS
        }
        annotations["vibrato"] = {"state": 1, "confidence": 2}
        annotations["uncertain"] = {"state": 1, "confidence": 1}
        core.append_annotations(csv_path, "R-TEST0001", 0.0, 1.0, annotations, core.LABELS)

        with open(csv_path, newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["vibrato_state"], "1")
        self.assertEqual(row["vibrato_confidence"], "2")
        self.assertEqual(row["uncertain_state"], "1")
        self.assertEqual(row["uncertain_confidence"], "1")
        self.assertEqual(row["straight_state"], "0")

    def test_existing_unclear_columns_are_renamed_and_data_is_preserved(self):
        csv_path = core.get_annotations_path(self.data_dir)
        old_labels = ["unclear" if label == "uncertain" else label for label in core.LABELS]
        old_columns = core._annotation_columns(old_labels)
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(old_columns)
            row = {column: "0" for column in old_columns}
            row.update({
                "recording_id": "R-TEST0001",
                "start_sec": "0.0",
                "end_sec": "1.0",
                "unclear_state": "1",
                "unclear_confidence": "2",
            })
            writer.writerow([row[column] for column in old_columns])

        core.init_annotations_csv(csv_path, core.LABELS)

        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            self.assertIn("uncertain_state", reader.fieldnames)
            self.assertNotIn("unclear_state", reader.fieldnames)
        self.assertEqual(row["uncertain_state"], "1")
        self.assertEqual(row["uncertain_confidence"], "2")
        self.assertEqual(row["vibrato_state"], "0")

    def test_recording_key_is_written_only_when_explicitly_requested(self):
        with (
            patch.object(core, "get_audio_files", return_value=[self.long_file]),
            patch.object(core, "load_audio_file", return_value=(np.zeros(20), 10)),
        ):
            state, error = core.init_state(self.data_dir, window_size=1.0, hop_size=0.5)

        self.assertIsNone(error)
        key_path = core.get_recording_key_path(self.data_dir)
        self.assertFalse(os.path.exists(key_path))
        core.write_recording_key(state["data_dir"], state["audio_files"], state["recording_ids"])
        self.assertTrue(os.path.exists(key_path))
        with open(key_path, newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["file"], os.path.basename(self.long_file))


if __name__ == "__main__":
    unittest.main()
