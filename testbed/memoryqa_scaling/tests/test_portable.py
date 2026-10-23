import contextlib
import hashlib
import io
import json
import socket
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from lib import download
from lib.common import ROOT, digest, manifest, relative_path
from lib.graphs import decode, encode, load_snapshot
from lib.validate import check_inputs, verify_results


class PortablePackageTests(unittest.TestCase):
    def test_manifest_has_exact_120_images_and_known_byte_total(self):
        spec=manifest()
        self.assertEqual(spec["image_count"],120)
        self.assertEqual(sum(r["size_bytes"] for r in spec["images"]),154616896)
        self.assertEqual(spec["archive_sha256"],"c51240395724b366e2fb8c071f3770c88b6de1621981b5ad68cbad9553ed0a18")

    def test_paths_reject_absolute_traversal_and_windows_separators(self):
        for path in ("/tmp/escape", "../escape", "assets/../../escape", "C:\\escape", "assets\\escape"):
            with self.subTest(path=path),self.assertRaises(ValueError):relative_path(path)

    def test_offline_plan_has_all_sources_at_each_size_and_no_network(self):
        with patch.object(socket.socket,"connect",side_effect=AssertionError("network forbidden")):
            result=check_inputs()
        self.assertEqual(result["tasks"],540)
        self.assertEqual([r["photos"] for r in result["levels"].values()],[40,80,120])

    def test_all_recorded_metrics_recompute_without_network(self):
        with patch.object(socket.socket,"connect",side_effect=AssertionError("network forbidden")):
            result=verify_results()
        self.assertTrue(result["all_six_cells_recomputed"])
        self.assertEqual(result["metrics"]["300"]["graphiti"]["strict_correct"],66)

    def test_recorded_grade_does_not_accept_a_changed_answer(self):
        from lib.validate import recorded_rows
        rows=recorded_rows()
        rows[0]["text"]="tampered answer"
        with patch("lib.validate.recorded_rows",return_value=rows),self.assertRaisesRegex(ValueError,"Answer/grade hash"):
            verify_results()

    def test_graph_snapshots_preserve_all_typed_properties(self):
        counts=[]
        for n in (100,200,300):
            snap=load_snapshot(n)
            props={k:snap[k] for k in ("nodes","edges")}
            self.assertEqual(encode(decode(props)),props)
            self.assertEqual(digest(props),snap["content_sha256"])
            counts.append((len(snap["nodes"]),len(snap["edges"])))
        self.assertEqual(counts,[(171,313),(311,554),(439,786)])

    def test_explicit_paid_opt_in_is_required_before_bootstrap(self):
        from lib.run import run
        with patch("lib.run.bootstrap",side_effect=AssertionError("bootstrap forbidden")):
            with self.assertRaisesRegex(ValueError,"--allow-paid"):run(100,"unused")

    def test_graph_restoration_requires_explicit_write_opt_in(self):
        from lib.graphs import restore_graphs
        with patch("lib.graphs.connection",side_effect=AssertionError("DB forbidden")):
            with self.assertRaisesRegex(ValueError,"--allow-db-write"):restore_graphs()

    def test_pinned_app_executes_both_conditions_with_mock_services(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from lib.app import bootstrap
        from lib.common import dataset,read,resolved_task
        from lib.original.live import execute_task,expected_sources
        from lib.original.usage import instrument_sdk
        from lib.read_only_database import read_only_database_scope
        from openai.resources.responses.responses import AsyncResponses
        with tempfile.TemporaryDirectory() as folder:
            config=bootstrap(100,folder)
            from PIL import Image
            picture=Path(folder)/"synthetic.jpg"
            Image.new("RGB",(3,3),"white").save(picture)
            image_sha=hashlib.sha256(picture.read_bytes()).hexdigest()
            from django.test import override_settings
            from integrations.ai_workers import graphiti_client,searching_graphiti
            data=dataset(100);wanted=expected_sources(data,data["db"])
            tasks=read(ROOT/"panel/history_100/tasks.json")
            pair=[next(t for t in tasks if t["condition"]==c) for c in ("full_history","graphiti")]
            name,source=next(iter(wanted.items()))
            memory={"id":"offline-fact","fact":"오프라인 사실","sources":[{"id":"offline-source","name":name,"text":source["text"]}]}
            async def create(client,**options):
                output=[]
                if options.get("tool_choice")=="auto":
                    output=[SimpleNamespace(type="function_call",name="search_family_memory",call_id="offline-call",arguments='{"query":"과거 가족 사실"}')]
                return SimpleNamespace(status="completed",output=output,output_text="오프라인 모의 답변",id="offline-response",
                    model=options["model"],service_tier=options.get("service_tier"),
                    usage=SimpleNamespace(model_dump=lambda:{"input_tokens":100,"output_tokens":10}))
            async def search(graph,family,queries,**kwargs):return [{"query":q,"memories":[memory]} for q in queries]
            with override_settings(OPENAI_API_KEY="offline-test-key",NEO4J_PASSWORD="offline-test-password"), \
                 patch.object(socket.socket,"connect",side_effect=AssertionError("network forbidden")), \
                 patch.object(AsyncResponses,"create",create), \
                 patch.object(graphiti_client,"create_graphiti",return_value=object()), \
                 patch.object(graphiti_client,"close_graphiti",new=AsyncMock()), \
                 patch.object(searching_graphiti,"search_many",side_effect=search), \
                 read_only_database_scope(),instrument_sdk():
                for task in pair:
                    synthetic_task={**task,"image_path":str(picture),"image_sha256":image_sha}
                    result=asyncio.run(execute_task(synthetic_task,config,data,
                        {"signature":"offline-only","family_id":data["db"]["family_id"]},wanted))
                    self.assertEqual(result["status"],"complete",result.get("error_type"))
                    self.assertTrue(result["usage"]["usage_complete"])
                    self.assertEqual(len(result["calls"]),1 if task["condition"]=="full_history" else 2)
                    if task["condition"]=="full_history":self.assertEqual(len(result["payload"]["가족기록"]),100)
                    else:self.assertEqual(result["provided_post_ids"],[source["post_key"]])


class DownloadTests(unittest.TestCase):
    def fixture(self):
        raw=b"synthetic public-image bytes"
        name=b"images/images/example.jpg"
        compressor=zlib.compressobj(wbits=-15)
        packed=compressor.compress(raw)+compressor.flush()
        header=struct.pack("<4s5H3I2H",b"PK\x03\x04",20,0,8,0,0,zlib.crc32(raw),len(packed),len(raw),len(name),0)
        blob=header+name+packed
        row={"image_id":"example","path":"assets/images/example.jpg","sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw),
            "archive_entry":{"offset":0,"compression":8,"compressed_size":len(packed),"size":len(raw),"crc32":zlib.crc32(raw),"name":name.decode()}}
        class Source:
            def fetch(self,start,length):return blob[start:start+length]
        return raw,row,Source()

    def test_selected_zip_entry_is_crc_and_sha_verified(self):
        raw,row,source=self.fixture()
        self.assertEqual(download.unpack_entry(source,row),raw)

    def test_wrong_checksum_is_rejected(self):
        _,row,source=self.fixture();row["sha256"]="0"*64
        with self.assertRaisesRegex(RuntimeError,"checksum"):download.unpack_entry(source,row)

    def test_server_ignoring_ranges_is_rejected_without_reading_archive(self):
        source=download.RangeSource({"archive_size":1000})
        class Response:
            status=200
            headers={}
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,*_):raise AssertionError("Full archive body must not be read")
        with patch.object(source,"transport",return_value={"href":"https://example.invalid/archive"}), \
             patch.object(download.urllib.request,"urlopen",return_value=Response()):
            with self.assertRaisesRegex(RuntimeError,"ignored Range"):source.fetch(0,30)

    def test_cached_photo_uses_no_network(self):
        raw,row,_=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/"example.jpg").write_bytes(raw)
            with patch.object(download,"manifest",return_value={"images":[row],"archive_size":1000}), \
                 patch.object(download.urllib.request,"urlopen",side_effect=AssertionError("network forbidden")), \
                 patch.object(download,"save"),contextlib.redirect_stdout(io.StringIO()):
                result=download.download_images(directory=folder)
        self.assertEqual((result["downloaded"],result["cached"],result["bytes_received"]),(0,1,0))

    def test_corrupt_photo_is_repaired_atomically(self):
        raw,row,_=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"example.jpg";path.write_bytes(b"corrupt")
            with patch.object(download,"manifest",return_value={"images":[row],"archive_size":1000}), \
                 patch.object(download,"unpack_entry",return_value=raw),patch.object(download,"save"), \
                 contextlib.redirect_stdout(io.StringIO()):
                result=download.download_images(directory=folder)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(list(Path(folder).glob("*.part")),[])
        self.assertEqual(result["downloaded"],1)

    def test_failed_download_does_not_replace_a_local_file(self):
        _,row,_=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"example.jpg";path.write_bytes(b"corrupt")
            with patch.object(download,"manifest",return_value={"images":[row],"archive_size":1000}), \
                 patch.object(download,"unpack_entry",side_effect=RuntimeError("checksum mismatch")):
                with self.assertRaisesRegex(RuntimeError,"checksum"):download.download_images(directory=folder)
            self.assertEqual(path.read_bytes(),b"corrupt")


if __name__=="__main__":unittest.main()
