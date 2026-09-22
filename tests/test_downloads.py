"""Download integrity and concurrent publication without network requests."""

import concurrent.futures
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest import mock

from gobench import strategies


class DownloadTests(unittest.TestCase):
    def test_concurrent_downloads_to_same_destination_both_succeed(self):
        payload = b"verified network data\n"
        opened = threading.Barrier(2)
        written = threading.Barrier(2)
        first_done = threading.Event()
        local = threading.local()

        class Response(io.BytesIO):
            def __exit__(self, *args):
                super().__exit__(*args)
                written.wait(timeout=5)
                if local.second and not first_done.wait(timeout=5):
                    raise TimeoutError("first download did not finish")

        def urlopen(request):
            opened.wait(timeout=5)
            return Response(payload)

        with TemporaryDirectory() as root:
            destination = Path(root) / "network.txt.gz"

            def download(second):
                local.second = second
                try:
                    strategies._download(
                        "https://example.invalid/network", destination,
                        hashlib.sha256(payload).hexdigest(), len(payload),
                    )
                finally:
                    if not second:
                        first_done.set()

            with (mock.patch.object(strategies.urllib.request, "urlopen", side_effect=urlopen),
                  concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool):
                futures = [pool.submit(download, second) for second in (False, True)]
                for future in futures:
                    future.result(timeout=10)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(list(Path(root).iterdir()), [destination])

    def test_failed_download_preserves_destination_and_cleans_temporary_file(self):
        payload = b"new network"
        for failure in ("size", "checksum", "transport"):
            with self.subTest(failure=failure), TemporaryDirectory() as root:
                destination = Path(root) / "network.txt.gz"
                destination.write_bytes(b"previous network")
                source = io.BytesIO(payload)
                if failure == "transport":
                    source.read = mock.Mock(side_effect=OSError("download interrupted"))
                digest = hashlib.sha256(payload).hexdigest() if failure != "checksum" else "0" * 64
                size = len(payload) if failure != "size" else len(payload) + 1
                with mock.patch.object(strategies.urllib.request, "urlopen", return_value=source):
                    with self.assertRaises(strategies.GoEngineError):
                        strategies._download("https://example.invalid/network", destination, digest, size)
                self.assertEqual(destination.read_bytes(), b"previous network")
                self.assertEqual(list(Path(root).iterdir()), [destination])
