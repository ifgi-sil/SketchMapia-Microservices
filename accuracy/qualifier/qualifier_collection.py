# -*- coding: utf-8 -*-
"""
Created on Thu Jan 25 13:00:03 2018

@author: Malumbo

This script loops through a list of qualifiers, initializing them 
and returning a list of qualifier functions that can be applied on 
any 'well formed' data.
"""
from qualifier.qualify_RCC8 import qualify_rcc8
from qualifier.qualify_RCC11 import qualify_rcc11
from qualifier.qualify_RegionStarVars import relative_direction_relations
from qualifier.qualify_Adjacency import qualify_Adjacency
from qualifier.qualify_relativeDist import qualify_relativeDist
from qualifier.qualify_OPRA import qualify_OPRA
from qualifier.qualify_DE9IM_linepolygon import qualify_DE9IM_linepolygon
from qualifier.qualify_LeftRight import qualify_LeftRight
from qualifier.qualify_street_topology import qualify_street_connectivity
from qualifier.qualify_linearOrdering import qualify_linear_ordering

# Maps each active qualifier function to its domain group. Used to filter
# which qualifiers run when analyzeQualitative receives a subset selection
# (buildings / streets / streetbuilding). Keep in sync with MEASURE_GROUP
# in accuracy/microservice/views.py.
QUALIFIER_GROUP = {
    'qualify_rcc8':                 'buildings',
    'qualify_DE9IM_linepolygon':    'streetbuilding',
    'qualify_LeftRight':            'streetbuilding',
    'qualify_OPRA':                 'streets',
    'qualify_street_connectivity':  'streets',
    'qualify_linear_ordering':      'streetbuilding',
}

def qualifier_functions(groups=None):
    """Return the qualifier functions to run.

    groups: optional iterable of domain-group names. When supplied, only
    qualifiers whose group is in the set are returned. When None/empty,
    the full list is returned (preserving the pre-change behaviour).
    """
    #  append qualifier for each aspect and return list
    qualifier_function_list = []

    # rcc8
    qualifier_function_list.append(qualify_rcc8)

    # rcc11
    #qualifier_function_list.append(qualify_rcc11)

    #Dimension extended 9 intersections
    qualifier_function_list.append(qualify_DE9IM_linepolygon)

    # RegionStarVars
    #dir_qualifier = relative_direction_relations(8)
    #qualifier_function_list.append(dir_qualifier.qualify_relative_direction)

    # relative distance
    # qualifier_function_list.append(qualify_relativeDist)

    # left-right relation of polygons and points with respect to line string objects
    qualifier_function_list.append(qualify_LeftRight)

    # street landmark adjacency
    #qualifier_function_list.append(qualify_Adjacency)

    # point based relative directions with OPRA
    qualifier_function_list.append(qualify_OPRA)

    # topology of Street segments based on DE9IM
    qualifier_function_list.append(qualify_street_connectivity)

    # Linear ordering between adjacent landmarks and streets
    qualifier_function_list.append(qualify_linear_ordering)

    if groups:
        wanted = set(groups)
        qualifier_function_list = [
            f for f in qualifier_function_list
            if QUALIFIER_GROUP.get(getattr(f, '__name__', '')) in wanted
        ]

    return qualifier_function_list