from pathlib import Path
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from runtime import safeio


class SafeDirectoryTests(unittest.TestCase):
    def ensure_private_directory(self, path: Path) -> Path:
        helper = getattr(safeio, "ensure_private_directory", None)
        self.assertIsNotNone(helper, "safe directory helper is missing")
        return helper(path)

    def test_creates_an_owner_only_directory_and_preserves_a_valid_one(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state" / "nested"
            self.assertEqual(target.absolute(), self.ensure_private_directory(target))
            inode = target.stat().st_ino
            marker = target / "existing"
            marker.write_text("preserved", encoding="utf-8")

            self.assertEqual(target.absolute(), self.ensure_private_directory(target))

            metadata = target.stat()
            self.assertTrue(stat.S_ISDIR(metadata.st_mode))
            self.assertEqual(0o700, stat.S_IMODE(metadata.st_mode))
            if hasattr(os, "getuid"):
                self.assertEqual(os.getuid(), metadata.st_uid)
            self.assertEqual(inode, metadata.st_ino)
            self.assertEqual("preserved", marker.read_text(encoding="utf-8"))

    def test_corrects_an_owned_directory_to_owner_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state"
            target.mkdir(mode=0o777)
            target.chmod(0o777)

            self.ensure_private_directory(target)

            self.assertEqual(0o700, stat.S_IMODE(target.stat().st_mode))

    def test_refuses_a_user_controlled_symlink_and_a_non_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            regular = root / "regular"
            regular.write_text("untouched", encoding="utf-8")

            for unsafe in (linked, regular):
                with self.subTest(path=unsafe), self.assertRaisesRegex(
                    ValueError, "unsafe state directory"
                ):
                    self.ensure_private_directory(unsafe)

            self.assertEqual("untouched", regular.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "getuid"), "ownership checks require getuid")
    def test_refuses_a_directory_not_owned_by_the_current_user(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state"
            target.mkdir()
            current_uid = os.getuid()
            with patch.object(safeio.os, "getuid", return_value=current_uid + 1), self.assertRaisesRegex(
                ValueError, "not owned by the current user"
            ):
                self.ensure_private_directory(target)


if __name__ == "__main__":
    unittest.main()
