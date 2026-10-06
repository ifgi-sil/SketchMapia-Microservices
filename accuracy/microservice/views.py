import copy

from django.shortcuts import render
import os
import json
from django.http import HttpResponse
from django.template import loader
from . import qualitativeAnalyser
import glob
from qualifier import qualify_map
import copy

#@app.route("/mmReceiver", methods=["POST", "GET"])
def mmGeoJsonReceiver(request):
    # template = loader.get_template('../templates/generalizingmaps.html')
    global MM_QCN_PATH
    global USER_PROJ_DIR
    #global USER_PROJ_DIR
    fileName_full = str(request.POST.get('metricFileName'))
    MMGeoJsonData = request.POST.get('MMGeoJsonData')
    #print(type(MMGeoJsonData))
    MMGeoJsonData = json.loads(MMGeoJsonData)
    # print("here svg file and content:",fileName_full, svgContent)
    fileName, extension = os.path.splitext(fileName_full)

    #smGeoJson = request.get_json()
    data_format = "geojson"
    map_type = "metric_map"

    MetricMap_QCNS = qualify_map.main_loader(fileName, MMGeoJsonData, data_format, map_type)
    # print(MetricMap_QCNS)
    # Get the absolute path of the accuracy folder
    accuracy_folder = os.path.dirname(os.path.abspath(__file__))

    # Get the parent directory (one level up)
    parent_directory = os.path.dirname(os.path.dirname(accuracy_folder))

    # Define the output folder path
    USER_PROJ_DIR = os.path.join(parent_directory, "QualitativeRelationsOutput")
    try:
        MM_QCN_PATH = os.path.join(USER_PROJ_DIR,fileName_full+".json")
        #filepath = './output/'+str("sketchMapID")+'.json'
        print("final file path. sm..",MM_QCN_PATH)

        if os.path.exists(MM_QCN_PATH):
            os.remove(MM_QCN_PATH)
        f = open(MM_QCN_PATH, "a+")
        f.write(json.dumps(MetricMap_QCNS,indent=4))
        f.close()
    except IOError:
        print("Metric map QCNs json path problem ")
    return HttpResponse(json.dumps(MetricMap_QCNS,indent=4))


"""
    - load sketch map geojson into qualifier 
"""


#@app.route("/smReceiver", methods=["POST", "GET"])
def smGeoJsonReceiver(request):
    # template = loader.get_template('../templates/generalizingmaps.html')
    global SM_QCN_PATH

    fileName_full = str(request.POST.get('sketchFileName'))
    SMGeoJsonData = request.POST.get('SMGeoJsonData')
    SMGeoJsonData = json.loads(SMGeoJsonData)
    # print("here svg file and content:",fileName_full, svgContent)
    fileName, extension = os.path.splitext(fileName_full)
    #print("here is SMGeoJsonData:",SMGeoJsonData)
    #smGeoJson = request.get_json()
    data_format = "geojson"
    map_type = "sketch_map"

    sketchMap_QCNS = qualify_map.main_loader(fileName, SMGeoJsonData, data_format, map_type)
    try:
        SM_QCN_PATH = os.path.join(USER_PROJ_DIR,fileName_full+".json")
        #filepath = './output/'+str("sketchMapID")+'.json'
        print("final file path. sm..",SM_QCN_PATH)

        if os.path.exists(SM_QCN_PATH):
            os.remove(SM_QCN_PATH)
        f = open(SM_QCN_PATH, "a+")
        f.write(json.dumps(sketchMap_QCNS,indent=4))
        f.close()
    except IOError:
        print("Sketch map QCNs json path problem ")
    return HttpResponse(json.dumps(sketchMap_QCNS, indent=4))

def clearFiles(request):

    files = glob.glob('QualitativeRelationsOutput/*')
    print("FILEFILEFILEFILEFILEEEEEEEEEEEEEEEEEEEEEEEE",files)

    for f in files:
        print(f)
        os.remove(f)
    return HttpResponse()




# Create your views here.
def analyzeQualitative(request):
    sketchFileName = str(request.POST.get('sketchFileName'))
    metricFileName = str(request.POST.get('metricFileName'))
    print ("check", sketchFileName, metricFileName)
    sketchmapdata = request.POST.get('sketchdata')
    metricmapdata = request.POST.get('metricdata')
    SMGeoJsonData = json.loads(sketchmapdata)
    MMGeoJsonData = json.loads(metricmapdata)
    data_format = "geojson"


    # ------------------------------------------------------------------
    # qa_groups is a comma-separated list from the Analyse modal naming
    # which domain groups to run. Supported values:
    #   buildings       -> RCC11
    #   streets         -> StreetTopology, OPRA
    #   streetbuilding  -> DE9IM, LeftRight, LinearOrdering
    # Missing / empty = run everything (keeps older callers working).
    # ------------------------------------------------------------------
    qa_groups_raw = (request.POST.get('qa_groups') or '').strip()
    if qa_groups_raw:
        selected_groups = {g.strip() for g in qa_groups_raw.split(',') if g.strip()}
    else:
        selected_groups = {"buildings", "streets", "streetbuilding"}

    # Only the qualifier functions whose group is in ``selected_groups``
    # are run inside main_loader, so unselected groups skip the pairwise
    # relation computation entirely (not just the counting below).
    sketchMapQCN_S =  qualify_map.main_loader(sketchFileName, SMGeoJsonData, data_format, "sketch_map", groups=selected_groups)
    metricMapQCN_S =  qualify_map.main_loader(metricFileName,MMGeoJsonData,data_format,"metric_map",   groups=selected_groups)
    sketchMapQCNs = copy.deepcopy(sketchMapQCN_S)
    metricMapQCNs = copy.deepcopy(metricMapQCN_S)

    # ------------------------------------------------------------------
    # Each sub-measure is wrapped in a helper that:
    #   - skips with reason "not selected" if its group isn't in qa_groups
    #   - catches any runtime exception (e.g. no route in dataset) and
    #     marks the sub-measure skipped with that reason.
    # Precision / recall are computed only over sub-measures that ran.
    # ------------------------------------------------------------------

    MEASURE_GROUP = {
        "rcc11":          "buildings",
        "streetTopology": "streets",
        "opra":           "streets",
        "de9im":          "streetbuilding",
        "leftRight":      "streetbuilding",
        "linearOrdering": "streetbuilding",
    }

    skipped = {}

    def _run_measure(name, fn):
        """Run a sub-measure. Skip if its group was not selected, or on exception."""
        group = MEASURE_GROUP.get(name)
        if group not in selected_groups:
            skipped[name] = "not selected"
            return None
        try:
            return fn()
        except Exception as exc:
            skipped[name] = str(exc) or exc.__class__.__name__
            print(sketchFileName, "SKIPPED", name, "->", skipped[name])
            return None

    # --- RCC11 (buildings-only) ---
    def _rcc11():
        tmm = qualitativeAnalyser.getTotalRelations_rcc8_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalRelations_rcc8_sm(sketchMapQCNs)
        correct = qualitativeAnalyser.getCorrectRelation_rcc8(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongRelations_rcc8(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no polygon features for RCC11")
        acc = (correct / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, correct, wrong, tmm - (correct + wrong), acc)
    rcc = _run_measure("rcc11", _rcc11)

    # --- Linear Ordering (route + buildings) ---
    def _lo():
        tmm = qualitativeAnalyser.getTotalLinearOrderingReltions_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalLinearOrderingReltions_sm(sketchMapQCNs)
        matched = qualitativeAnalyser.getCorrectRelation_linearOrdering(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongRelations_linearOrdering(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no linear-ordering relations (route or polygons missing)")
        acc = (matched / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, matched, wrong, tmm - (matched + wrong), acc)
    lo = _run_measure("linearOrdering", _lo)

    # --- Left/Right (route + buildings) ---
    def _lr():
        tmm = qualitativeAnalyser.getTotalLeftRightRelations_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalLeftRightRelations_sm(sketchMapQCNs)
        matched = qualitativeAnalyser.getCorrectrelations_leftRight(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongCorrectrelations_leftRight(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no left-right relations (route or polygons missing)")
        acc = (matched / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, matched, wrong, tmm - (matched + wrong), acc)
    lr = _run_measure("leftRight", _lr)

    # --- DE9IM (line x polygon) ---
    def _de9im():
        tmm = qualitativeAnalyser.getTotalDE9IMRelations_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalDE9IMRelations_sm(sketchMapQCNs)
        matched = qualitativeAnalyser.getCorrectrelations_DE9IM(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongCorrectrelations_DE9IM(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no street-building relations (need ≥1 line and ≥1 polygon)")
        acc = (matched / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, matched, wrong, tmm - (matched + wrong), acc)
    de9im = _run_measure("de9im", _de9im)

    # --- Street Topology (streets-only) ---
    def _stop():
        tmm = qualitativeAnalyser.getTotalStreetTopology_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalStreetTopology_sm(sketchMapQCNs)
        matched = qualitativeAnalyser.getCorrectrelations_streetTopology(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongCorrectrelations_streetTopology(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no street-topology relations (need ≥2 lines)")
        acc = (matched / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, matched, wrong, tmm - (matched + wrong), acc)
    stop = _run_measure("streetTopology", _stop)

    # --- OPRA (streets-only, at junctions) ---
    def _opra():
        tmm = qualitativeAnalyser.getTotalOPRA_mm(metricMapQCNs)
        tsm = qualitativeAnalyser.getTotalOPRA_sm(sketchMapQCNs)
        matched = qualitativeAnalyser.getCorrectrelations_opra(sketchMapQCNs, metricMapQCNs)
        wrong = qualitativeAnalyser.getWrongCorrectrelations_opra(sketchMapQCNs, metricMapQCNs)
        if tsm == 0 and tmm == 0:
            raise RuntimeError("no OPRA relations (need ≥2 connected lines)")
        acc = (matched / tsm) * 100 if tsm else 0.00
        return (tmm, tsm, matched, wrong, tmm - (matched + wrong), acc)
    opra = _run_measure("opra", _opra)

    # ------------------------------------------------------------------
    # Precision / recall are pooled across only the sub-measures that ran.
    # ------------------------------------------------------------------
    ran = [m for m in (rcc, lo, lr, de9im, stop, opra) if m is not None]
    sum_mm      = sum(m[0] for m in ran)
    sum_sm      = sum(m[1] for m in ran)
    sum_matched = sum(m[2] for m in ran)
    precision = (sum_matched / sum_sm) if sum_sm else 0.0
    recall    = (sum_matched / sum_mm) if sum_mm else 0.0

    print(sketchFileName, "precision....:", precision, "recall....:", recall,
          "skipped:", list(skipped.keys()))

    # Expand each measure's tuple into the flat key names the frontend reads.
    # When a measure was skipped the fields are set to None so the UI can show
    # "—" and the CSV writers can emit blank cells.
    def _unpack(m, keys):
        if m is None:
            return {k: None for k in keys}
        tmm, tsm, matched, wrong, missing, acc = m
        return dict(zip(keys, [tmm, tsm, matched, wrong, missing, round(acc, 2)]))

    rcc_fields = _unpack(rcc, [
        "totalRCC11Relations_mm", "totalRCC11Relations",
        "correctRCC11Relations", "wrongMatchedRCC11rels",
        "missingRCC11rels", "correctnessAccuracy_rcc11"
    ])
    lo_fields = _unpack(lo, [
        "total_lO_rels_mm", "total_LO_rels_sm",
        "matched_LO_rels", "wrong_matched_LO_rels",
        "missing_LO_rels", "correctnessAccuracy_LO"
    ])
    lr_fields = _unpack(lr, [
        "total_LR_rels_mm", "total_LR_rels_sm",
        "matched_LR_rels", "wrong_matched_LR_rels",
        "missing_LR_rels", "correctnessAccuracy_LR"
    ])
    de9im_fields = _unpack(de9im, [
        "total_DE9IM_rels_mm", "total_DE9IM_rels_sm",
        "matched_DE9IM_rels", "wrong_matched_DE9IM_rels",
        "missing_DE9IM_rels", "correctnessAccuracy_DE9IM"
    ])
    stop_fields = _unpack(stop, [
        "total_streetTop_rels_mm", "total_streetTop_rels_sm",
        "matched_streetTop_rels", "wrong_matched_streetTop_rels",
        "missing_streetTop_rels", "correctnessAccuracy_streetTop"
    ])
    opra_fields = _unpack(opra, [
        "total_opra_rels_mm", "total_opra_rels_sm",
        "matched_opra_rels", "wrong_matched_opra_rels",
        "missing_opra_rels", "correctnessAccuracy_opra"
    ])

    qualitative_results = {"sketchMapID": sketchFileName}
    qualitative_results.update(rcc_fields)
    qualitative_results.update(lo_fields)
    qualitative_results.update(lr_fields)
    qualitative_results.update(de9im_fields)
    qualitative_results.update(stop_fields)
    qualitative_results.update(opra_fields)
    qualitative_results["precision"] = round(precision, 2)
    qualitative_results["recall"] = round(recall, 2)
    qualitative_results["f_score"] = "nil"
    qualitative_results["skipped"] = skipped
    # breakpoint()
    response_data = {
        "qualitative_results": qualitative_results,
        "smqcn": sketchMapQCN_S,
        "mmqcn": metricMapQCN_S
    }

    print (sketchFileName,"DONEEEEEEEEEEEEEEEEE")

    return HttpResponse(json.dumps(response_data), content_type="application/json")
