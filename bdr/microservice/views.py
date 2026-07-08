import json
import numpy as np
import geopandas as gpd
import skimage as sk
import sklearn.metrics as met
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def compute_mbr_points(dict_geometry, r_buffer = 1):
    """
    This function will compute the 8 points from the Minimum Bounding 
    Rectangle drawn on a Polygon or MultiPolygon, 
    if it is a PointMarker, it will draw a buffer of 1 pixel radius
    and then extract the 8 points from the MBR.
    """
    coords = dict_geometry["coordinates"][0]
    if dict_geometry["type"] == "Polygon":
        x_min, y_min = np.inf, np.inf
        x_max, y_max = -np.inf, -np.inf
        for c in coords:
            x, y = c
            if x < x_min:
                x_min = x
            if x > x_max:
                x_max = x
            if y < y_min:
                y_min = y
            if y > y_max:
                y_max = y
    elif dict_geometry["type"] == "Point":
        x, y = coords
        x_min, x_max = x - r_buffer, x + r_buffer
        y_min, y_max = y -r_buffer, y + r_buffer
    else:
        return None
    return [
        [x_min, y_max], [(x_min + x_max) / 2, y_max], 
        [x_max, y_max],
        [x_max, (y_min + y_max) / 2], [x_max, y_min],
        [(x_min + x_max) / 2, y_min],
        [x_min, y_min], 
        [x_min, (y_min + y_max) / 2] 
    ]


def junctions_detector(data, map_type):
    """
    Detects automatically the junctions on a base map or sketch map.
    """
    junctions = {} # stores the coordinates and the intersecting roads ids for each junction
    dict_mbr = {} # stores the MBR coordinates for each junction on the base map
    j_id = 0 # self-generated id for junctions
    for i in range(data.shape[0]): # for each line
        l1_id = data[['id']].iloc[i, 0]
        l1_coords = data[['geometry']].iloc[i, 0]["coordinates"]
        l1_ends = [l1_coords[0], l1_coords[-1]] # only the first and last points of the line
        for j in range(i+1, data.shape[0]): # for each other unexplored line
            l2_id = data[['id']].iloc[j, 0]
            l2_coords = data[['geometry']].iloc[j, 0]["coordinates"]
            l2_ends = [l2_coords[0], l2_coords[-1]]
            for end1 in l1_ends: # try to find a common end between l1 & l2
                    for end2 in l2_ends:
                        if end1 == end2:
                            new_junc = True # in a first time, suppose that the junction is new
                            for junc in junctions.keys():
                                if end1 == junctions[junc][0]: # if this junction was already detected
                                    if l1_id in junctions[junc][1] and not l2_id in junctions[junc][1]: # add the missing id to the line ids
                                        junctions[junc][1].append(l2_id)
                                    elif l2_id in junctions[junc][1] and not l1_id in junctions[junc][1]:
                                        junctions[junc][1].append(l1_id)
                                    new_junc = False # finally this junction is already known
                                    continue
                            if new_junc: # if finally this junction is really new
                                if map_type == 'basemap':
                                    junctions['JB'+str(j_id)] = [end1, [l1_id, l2_id]] # add [JBx]: [[coords], [id_lines]] in junctions
                                else: # map_type == 'sketchmap'
                                    junctions['JS'+str(j_id)] = [end1, [l1_id, l2_id]] # add [JSx]: [[coords], [id_lines]] in junctions
                                j_id += 1
    # MBRs calculation for the base map
    for junc in junctions.keys():
        point = {'type': 'Point', 'coordinates': [junctions[junc][0]]} # dict representing a geometry
        dict_mbr[junc] = compute_mbr_points(point)
    return junctions, dict_mbr


def compute_LandmarksBDR(basemap_geojson, sketchmap_geojson):
    """
    Returns a JSON file with the 6 BDR measures calculated on landmarks.
    """
    # Data preparation
    bsm_data = gpd.GeoDataFrame(columns=["id", "SketchAlign", "geometry"]).set_geometry("geometry")
    skm_data = gpd.GeoDataFrame(columns=["id", "geometry"]).set_geometry("geometry")
    dict_align = {} # stores the (base map id, sketch map id) pairs
    X = [] # coordinates of points on the base map
    Y = [] # coordinates of points on the sketch map

    # Sketch map: extraction of the drawn landmarks
    for j in range(len(sketchmap_geojson["features"])): # fills skm_data
        geometry_j = sketchmap_geojson["features"][j]["geometry"]
        if geometry_j["type"] in ("Polygon", "Point"): # only 1:1 polygons/points considered
            id_j = sketchmap_geojson["features"][j]["properties"]["id"]
            skm_data.loc[skm_data.shape[0]] = [id_j, geometry_j]

    # Base map: creation of a subdataset with only 1:1 aligned polygons
    for i in range(len(basemap_geojson["features"])): # fills bsm_data
        geometry_i = basemap_geojson["features"][i]["geometry"]
        if geometry_i["type"] in ("Polygon", "Point"): # only 1:1 polygons/points considered
            aligned_i = basemap_geojson["features"][i]["properties"]["aligned"]
            if aligned_i:
                SketchAlign_i = basemap_geojson["features"][i]["properties"]["SketchAlign"]
                if type(SketchAlign_i) != list or ( type(SketchAlign_i) == list and len(SketchAlign_i) == 1 ):
                    id_i = basemap_geojson["features"][i]["properties"]["id"]
                    bsm_data.loc[bsm_data.shape[0]] = [id_i, SketchAlign_i, geometry_i]

    # Landmarks alignment
                    if type(SketchAlign_i) == list:
                        dict_align[id_i] = int(SketchAlign_i[0][1:]) # landmark id on sketch map saved without 'S'
                    else: # type String
                        dict_align[id_i] = int(SketchAlign_i[1:])

    # MBRs calculation for the base map & sketch map
                    skm_id = dict_align[id_i]
                    for k in range(skm_data.shape[0]):
                        if str(skm_data[['id']].iloc[k, 0]) == str(skm_id):
                            skm_geom = skm_data[['geometry']].iloc[k, 0] # geometry corresponding to skm_id
                    bsm_coords_mbr = compute_mbr_points(geometry_i)
                    skm_coords_mbr = compute_mbr_points(skm_geom)
                    X.extend(bsm_coords_mbr)
                    Y.extend(skm_coords_mbr)

    # Estimation of the transformation parameters
    X, Y = np.array(X), np.array(Y)
    tform = sk.transform.SimilarityTransform()
    tform.estimate(X, Y)
    predicted_Y = tform(X)

    # Computation of the 6 BDR measures
    A, B = Y[:, 0], Y[:, 1]
    pred_A, pred_B = predicted_Y[:, 0], predicted_Y[:, 1]
    mean_A, mean_B = np.mean(A), np.mean(B)
    r = 1 - np.sum( (A-pred_A)**2 + (B-pred_B)**2 ) / np.sum( (A-mean_A)**2 + (B-mean_B)**2 )
    DI = 100 * np.sqrt(1 - r**2)
    phi = tform.scale
    theta = np.degrees(tform.rotation)
    alpha1, alpha2 = tform.translation 
    return {
        'r': round(r, 4),
        'DI': round(DI, 4),
        'phi': round(phi, 4),
        'theta': round(theta, 4),
        'alpha1': round(alpha1, 4),
        'alpha2': round(alpha2, 4)
    }


def compute_JunctionsBDR(basemap_geojson, sketchmap_geojson):
    """
    Returns a JSON file with the 6 BDR measures calculated on junctions.
    """
    # Data preparation
    bsm_data = gpd.GeoDataFrame(columns=["id", "SketchAlign", "geometry"]).set_geometry("geometry")
    skm_data = gpd.GeoDataFrame(columns=["id", "geometry"]).set_geometry("geometry")
    X = [] # coordinates of points on the base map
    Y = [] # coordinates of points on the sketch map

    # Sketch map: extraction of the drawn landmarks
    for j in range(len(sketchmap_geojson["features"])): # fills skm_data  
        geometry_j = sketchmap_geojson["features"][j]["geometry"]
        if geometry_j["type"] == "LineString": # only 1:1 lines considered
            id_j = sketchmap_geojson["features"][j]["properties"]["id"]
            skm_data.loc[skm_data.shape[0]] = [id_j, geometry_j]

    # Base map: creation of a subdataset with only 1:1 aligned polygons
    for i in range(len(basemap_geojson["features"])): # fills bsm_data
        geometry_i = basemap_geojson["features"][i]["geometry"]
        if geometry_i["type"] == "LineString": # only 1:1 lines considered
            aligned_i = basemap_geojson["features"][i]["properties"]["aligned"]
            if aligned_i:
                SketchAlign_i = basemap_geojson["features"][i]["properties"]["SketchAlign"]
                if type(SketchAlign_i) != list or ( type(SketchAlign_i) == list and len(SketchAlign_i) == 1 ):
                    id_i = basemap_geojson["features"][i]["properties"]["id"]
                    bsm_data.loc[bsm_data.shape[0]] = [id_i, SketchAlign_i, geometry_i]

    # Detection of junctions
    bsm_junctions, bsm_dict_mbr = junctions_detector(bsm_data, "basemap")
    skm_junctions, skm_dict_mbr = junctions_detector(skm_data, "sketchmap")
    
    # Junctions alignment
    for bsm_junc in bsm_junctions.keys():
        bsm_id_lines = bsm_junctions[bsm_junc][1]
        for skm_junc in skm_junctions.keys():
            skm_id_lines = skm_junctions[skm_junc][1]
            if set(skm_id_lines) <= set(bsm_id_lines): # if all the skm_id_lines included in bsm_id_lines
                bsm_coords_mbr = bsm_dict_mbr[bsm_junc]
                skm_coords_mbr = skm_dict_mbr[skm_junc]
                X.extend(bsm_coords_mbr)
                Y.extend(skm_coords_mbr)

    # Estimation of the transformation parameters
    X, Y = np.array(X), np.array(Y)
    tform = sk.transform.SimilarityTransform()
    tform.estimate(X, Y)
    predicted_Y = tform(X)

    # Computation of the 6 BDR measures
    A, B = Y[:, 0], Y[:, 1]
    pred_A, pred_B = predicted_Y[:, 0], predicted_Y[:, 1]
    mean_A, mean_B = np.mean(A), np.mean(B)
    r = 1 - np.sum( (A-pred_A)**2 + (B-pred_B)**2 ) / np.sum( (A-mean_A)**2 + (B-mean_B)**2 )
    DI = 100 * np.sqrt(1 - r**2)
    phi = tform.scale
    theta = np.degrees(tform.rotation)
    alpha1, alpha2 = tform.translation 
    return {
        'r': round(r, 4),
        'DI': round(DI, 4),
        'phi': round(phi, 4),
        'theta': round(theta, 4),
        'alpha1': round(alpha1, 4),
        'alpha2': round(alpha2, 4)
    }


@csrf_exempt
def calculateLandmarksBDR(request):
    """ 
    This is the function that Django will call when the frontend 
    sends a POST request to /bdr/calculateLandmarksBDR/ 
    It reads the two geoJSON payloads and then passes them to 
    compute_bdr, and then sends then back as JSON.

    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status = 405)
    try:
        basemap_geojson = json.loads(request.POST.get('basemapdata', '{}'))
        sketchmap_geojson = json.loads(request.POST.get('sketchmapdata', '{}'))
        result = compute_LandmarksBDR(basemap_geojson, sketchmap_geojson)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status = 500)
    

@csrf_exempt
def calculateJunctionsBDR(request):
    """ 
    This is the function that Django will call when the frontend 
    sends a POST request to /bdr/calculateLandmarksBDR/ 
    It reads the two geoJSON payloads and then passes them to 
    compute_bdr, and then sends then back as JSON.

    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status = 405)
    try:
        basemap_geojson = json.loads(request.POST.get('basemapdata', '{}'))
        sketchmap_geojson = json.loads(request.POST.get('sketchmapdata', '{}'))
        result = compute_JunctionsBDR(basemap_geojson, sketchmap_geojson)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status = 500)