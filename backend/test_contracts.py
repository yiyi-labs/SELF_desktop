import copy
import io
import json
import unittest
from PIL import Image
from pydantic import ValidationError
from contracts import Plan, Snapshot, validate_plan
from deepseek_client import parse_response, request_body, ModelFailure

def snapshot():
    return Snapshot(requestId="test-1", snapshotId="snap-1", assetId="sample", assetVersion="v1", textureVersion="t1",
        sceneRevision=2, regionVersion=1, viewRevision=0, view={"yaw":0.0}, userText="试色",
        regions=[{"regionId":"lip","description":"确认区域","semantic":"confirmed-lips"}],
        layers=[{"layerId":"layer-1","regionId":"lip","presetId":"rose","intensityLevel":"light"}],
        protectedRegionIds=[], uploadAuthorized=True)

def plan():
    return {"decision":"edit","shortMessage":"可以试一点颜色，由你决定。","operations":[{
        "operation":"set_digital_tint","regionId":"lip","presetId":"rose","intensityLevel":"light"}],
        "explanationRefs":[],"question":""}

def response(value):
    return {"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[{"type":"function","function":{
        "name":"propose_edit_plan","arguments":json.dumps(value)}}]}}]}

class Contracts(unittest.TestCase):
    def test_valid_candidate_has_no_authorization(self):
        self.assertEqual(parse_response(response(plan()),snapshot()).operations[0].regionId,"lip")
    def test_unknown_and_extra_fields(self):
        for key,value in (("operation","execute_code"),("regionId","invented"),("presetId","brand"),
                          ("intensityLevel","infinite"),("productProfileId","unverified"),("authorization",True)):
            with self.subTest(key=key):
                p=plan();p["operations"][0][key]=value
                with self.assertRaises(ModelFailure):parse_response(response(p),snapshot())
    def test_support_cannot_edit(self):
        p=plan();p["decision"]="support"
        with self.assertRaises(ModelFailure):parse_response(response(p),snapshot())
    def test_remove_checks_matching_layer(self):
        p=plan();op=p["operations"][0];op.update(operation="remove_effect",layerId="layer-1",intensityLevel="none")
        parse_response(response(p),snapshot())
        for key,value in (("layerId","missing"),("intensityLevel","light"),("presetId","terracotta")):
            q=copy.deepcopy(p);q["operations"][0][key]=value
            with self.assertRaises(ModelFailure):parse_response(response(q),snapshot())
    def test_truncated_empty_duplicate_wrong_tool(self):
        for kind in ("truncated","empty","duplicate","wrong","broken"):
            r=response(plan());choice=r["choices"][0]
            if kind=="truncated":choice["finish_reason"]="length"
            if kind=="empty":choice["message"]["tool_calls"]=[]
            if kind=="duplicate":choice["message"]["tool_calls"]*=2
            if kind=="wrong":choice["message"]["tool_calls"][0]["function"]["name"]="execute"
            if kind=="broken":choice["message"]["tool_calls"][0]["function"]["arguments"]="{"
            with self.assertRaises(ModelFailure):parse_response(r,snapshot())
    def test_upload_denial_is_rejected(self):
        s=snapshot().model_dump();s["uploadAuthorized"]=False
        with self.assertRaises(ValidationError):Snapshot.model_validate(s)
    def test_image_is_real_image_block_not_text(self):
        out=io.BytesIO();Image.new("RGB",(32,32),"red").save(out,format="PNG")
        body=request_body(snapshot(),[out.getvalue()],"deepseek-flash")
        self.assertEqual(body["thinking"],{"type":"disabled"})
        block=body["messages"][1]["content"][1]
        self.assertEqual(block["type"],"image_url")
        self.assertTrue(block["image_url"]["url"].startswith("data:image/png;base64,"))
    def test_invalid_image_rejected(self):
        with self.assertRaises(ModelFailure):request_body(snapshot(),[b"not an image"],"deepseek-flash")
    def test_explanation_reference_must_exist(self):
        p=plan();p["explanationRefs"]=["invented"]
        with self.assertRaises(ModelFailure):parse_response(response(p),snapshot())

    def test_new_tint_cannot_reuse_existing_layer_id(self):
        # Regression from the first real vision+tool response: the existing
        # layer is context, not the identity of a newly proposed layer.
        p=plan();p["operations"][0]["layerId"]="layer-1"
        with self.assertRaises(ModelFailure):parse_response(response(p),snapshot())

    def test_edit_cannot_also_request_clarification(self):
        p=plan();p["question"]="是否新增？"
        with self.assertRaises(ModelFailure):parse_response(response(p),snapshot())

if __name__=="__main__":unittest.main(verbosity=2)
