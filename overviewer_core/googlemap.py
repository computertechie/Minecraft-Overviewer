#    This file is part of the Minecraft Overviewer.
#
#    Minecraft Overviewer is free software: you can redistribute it and/or
#    modify it under the terms of the GNU General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or (at
#    your option) any later version.
#
#    Minecraft Overviewer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
#    Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with the Overviewer.  If not, see <http://www.gnu.org/licenses/>.

import os
import os.path
import stat
import cPickle
import Image
import shutil
from time import strftime, localtime
import json

import util
from c_overviewer import get_render_mode_inheritance, get_render_mode_info
import overviewer_version

"""
This module has routines related to generating a Google Maps-based
interface out of a set of tiles.

"""

def mirror_dir(src, dst, entities=None):
    '''copies all of the entities from src to dst'''
    if not os.path.exists(dst):
        os.mkdir(dst)
    if entities and type(entities) != list: raise Exception("Expected a list, got a %r instead" % type(entities))
    
    # files which are problematic and should not be copied
    # usually, generated by the OS
    skip_files = ['Thumbs.db', '.DS_Store']
    
    for entry in os.listdir(src):
        if entry in skip_files:
            continue
        if entities and entry not in entities:
            continue
        
        if os.path.isdir(os.path.join(src,entry)):
            mirror_dir(os.path.join(src, entry), os.path.join(dst, entry))
        elif os.path.isfile(os.path.join(src,entry)):
            try:
                shutil.copy(os.path.join(src, entry), os.path.join(dst, entry))
            except IOError as outer: 
                try:
                    # maybe permission problems?
                    src_stat = os.stat(os.path.join(src, entry))
                    os.chmod(os.path.join(src, entry), src_stat.st_mode | stat.S_IRUSR)
                    dst_stat = os.stat(os.path.join(dst, entry))
                    os.chmod(os.path.join(dst, entry), dst_stat.st_mode | stat.S_IWUSR)
                except OSError: # we don't care if this fails
                    pass
                shutil.copy(os.path.join(src, entry), os.path.join(dst, entry))
                # if this stills throws an error, let it propagate up

class MapGen(object):
    def __init__(self, quadtrees, configInfo):
        """Generates a Google Maps interface for the given list of
        quadtrees. All of the quadtrees must have the same destdir,
        image format, and world. 
        Note:tiledir for each quadtree should be unique. By default the tiledir is determined by the rendermode"""
        
        self.skipjs = configInfo.get('skipjs', False)
        self.nosigns = configInfo.get('nosigns', False)
        self.web_assets_hook = configInfo.get('web_assets_hook', None)
        self.web_assets_path = configInfo.get('web_assets_path', None)
        self.bg_color = configInfo.get('bg_color')
        self.north_direction = configInfo.get('north_direction', 'lower-left')
        
        if not len(quadtrees) > 0:
            raise ValueError("there must be at least one quadtree to work on")
        
        self.destdir = quadtrees[0].destdir
        self.world = quadtrees[0].world
        self.p = quadtrees[0].p
        for i in quadtrees:
            if i.destdir != self.destdir or i.world != self.world:
                raise ValueError("all the given quadtrees must have the same destdir and world")
        
        self.quadtrees = quadtrees
    
    def go(self, procs):
        """Writes out config.js, marker.js, and region.js
        Copies web assets into the destdir"""
        zoomlevel = self.p

        bgcolor = (int(self.bg_color[1:3],16), int(self.bg_color[3:5],16), int(self.bg_color[5:7],16), 0)
        blank = Image.new("RGBA", (1,1), bgcolor)
        # Write a blank image
        for quadtree in self.quadtrees:
            tileDir = os.path.join(self.destdir, quadtree.tiledir)
            if not os.path.exists(tileDir): os.mkdir(tileDir)
            blank.save(os.path.join(tileDir, "blank."+quadtree.imgformat))

        # copy web assets into destdir:
        global_assets = os.path.join(util.get_program_path(), "overviewer_core", "data", "web_assets")
        if not os.path.isdir(global_assets):
            global_assets = os.path.join(util.get_program_path(), "web_assets")
        mirror_dir(global_assets, self.destdir)
        
        # do the same with the local copy, if we have it
        if self.web_assets_path:
            mirror_dir(self.web_assets_path, self.destdir)
        
        # replace the config js stuff
        config = open(os.path.join(self.destdir, 'overviewerConfig.js'), 'r').read()
        config = config.replace(
                "{minzoom}", str(0))
        config = config.replace(
                "{maxzoom}", str(zoomlevel))
        config = config.replace(
                "{zoomlevels}", str(zoomlevel))
        config = config.replace(
                "{north_direction}", self.north_direction)
        
        config = config.replace("{spawn_coords}",
                                json.dumps(list(self.world.spawn)))

        #config = config.replace("{bg_color}", self.bg_color)
        
        # helper function to get a label for the given rendermode
        def get_render_mode_label(rendermode):
            info = get_render_mode_info(rendermode)
            if 'label' in info:
                return info['label']
            return rendermode.capitalize()
        
        # create generated map type data, from given quadtrees
        maptypedata = map(lambda q: {'label' : get_render_mode_label(q.rendermode),
                                     'shortname' : q.rendermode,
                                     'path' : q.tiledir,
                                     'bg_color': self.bg_color,
                                     'overlay' : 'overlay' in get_render_mode_inheritance(q.rendermode),
                                     'imgformat' : q.imgformat},
                          self.quadtrees)
        config = config.replace("{maptypedata}", json.dumps(maptypedata))
        
        with open(os.path.join(self.destdir, "overviewerConfig.js"), 'w') as output:
            output.write(config)

        # Add time and version in index.html
        indexpath = os.path.join(self.destdir, "index.html")

        index = open(indexpath, 'r').read()
        index = index.replace("{title}", "%s &mdash; Minecraft Overviewer" % self.world.name)
        index = index.replace("{time}", str(strftime("%a, %d %b %Y %H:%M:%S %Z", localtime())))
        versionstr = "%s (%s)" % (overviewer_version.VERSION, overviewer_version.HASH[:7])
        index = index.replace("{version}", versionstr)

        with open(os.path.join(self.destdir, "index.html"), 'w') as output:
            output.write(index)

        if self.skipjs:
            if self.web_assets_hook:
                self.web_assets_hook(self)
            return


    def finalize(self):
        # since we will only discover PointsOfInterest in chunks that need to be 
        # [re]rendered, POIs like signs in unchanged chunks will not be listed
        # in self.world.POI.  To make sure we don't remove these from markers.js
        # we need to merge self.world.POI with the persistant data in world.PersistentData

        self.world.POI += filter(lambda x: x['type'] != 'spawn', self.world.persistentData['POI'])
        
        if self.nosigns:
            markers = filter(lambda x: x['type'] != 'sign', self.world.POI)
        else:
            markers = self.world.POI

        # save persistent data
        self.world.persistentData['POI'] = self.world.POI
        self.world.persistentData['north_direction'] = self.world.north_direction
        with open(self.world.pickleFile,"wb") as f:
            cPickle.dump(self.world.persistentData,f)

        
        # the rest of the function is javascript stuff
        if self.skipjs:
            return

        # write out the default marker table
        with open(os.path.join(self.destdir, "markers.js"), 'w') as output:
            output.write("overviewer.collections.markerDatas.push([\n")
            for marker in markers:
                output.write(json.dumps(marker))
                if marker != markers[-1]:
                    output.write(",")
                output.write("\n")
            output.write("]);\n")
        
        # write out the default (empty, but documented) region table
        with open(os.path.join(self.destdir, "regions.js"), 'w') as output:
            output.write('overviewer.collections.regionDatas.push([\n')
            output.write('  // {"color": "#FFAA00", "opacity": 0.5, "closed": true, "path": [\n')
            output.write('  //   {"x": 0, "y": 0, "z": 0},\n')
            output.write('  //   {"x": 0, "y": 10, "z": 0},\n')
            output.write('  //   {"x": 0, "y": 0, "z": 10}\n')
            output.write('  // ]},\n')
            output.write(']);')
        
