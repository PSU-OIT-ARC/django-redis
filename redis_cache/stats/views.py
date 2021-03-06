# -*- coding: utf-8 -*-
# Copyright (c) 2011 Andrei Antoukh <niwi@niwi.be>

from django.views.generic import View
from django.shortcuts import render_to_response, get_object_or_404
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.template import RequestContext
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator

from redis.connection import UnixDomainSocketConnection, Connection
from redis.connection import DefaultParser

from ..util import load_class
from ..pool import get_or_create_connection_pool

import redis, re

class RedisStatsView(View):
    dbs_rx = re.compile(r'^db(\d+)$', flags=re.U)
    has_redis_cache = True

    def __init__(self, *args, **kwargs):
        if not hasattr(settings, "CACHES"):
            self.has_redis_cache = False

        if not hasattr(self, 'caches'):
            self.__class__.caches = self.get_caches()

        super(RedisStatsView, self).__init__(*args, **kwargs)
    
    def get_caches(self):
        caches = {}
        for name, options in getattr(settings, 'CACHES').iteritems():
            if 'BACKEND' not in options or 'RedisCache' not in options['BACKEND']:
                continue

            cachedict = {'unix_socket_path': None}
            servers = options.get('LOCATION', 'localhost:6379')

            if type(servers) not in [list, tuple]:
                servers = [servers]

            for server in servers:
                try:
                    if ":" in server:
                        try:
                            host, port, db = server.split(':')
                        except ValueError:
                            host, post = server.split(':')
                            db = 0

                        cachedict['host'] = host
                        cachedict['port'] = int(port)
                        cachedict['db'] = int(db)
                    else:
                        cachedict['port'] = cachedict['host'] = None
                        cachedict['unix_socket_path'] = server
                except (ValueError, TypeError):
                    raise ImproperlyConfigured("port value must be an integer")

                caches['%s@%s' % (name, server)] = cachedict
        return caches

    def get_info(self):
        if not self.has_redis_cache:
            return {}

        def parse_dbs(infoobject):
            dbs = {}
            for key, value in infoobject.iteritems():
                rx_match = self.dbs_rx.match(key)
                if rx_match:
                    dbs[str(rx_match.group(1))] = value

            return dbs
        
        global pools

        caches_info = {}
        for name, options in self.caches.iteritems():
            _pool_cls = load_class(options.get(
                'CONNECTION_POOL_CLASS', 'redis.connection.ConnectionPool'))
            rclient = redis.Redis(
                connection_pool=get_or_create_connection_pool(_pool_cls))

            caches_info[name] = rclient.info()
            caches_info[name]['dbs'] = parse_dbs(caches_info[name])
            caches_info[name]['options'] = options

        return caches_info

    def get(self, request):
        return render_to_response("redis_cache/stats.html", {},
            context_instance=RequestContext(request))
    
    def post(self, request):
        context = {'info':self.get_info()}
        return render_to_response("redis_cache/stats_include.html", context,
            context_instance=RequestContext(request))

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(RedisStatsView, self).dispatch(*args, **kwargs)
