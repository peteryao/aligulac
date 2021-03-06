import os
from datetime import datetime

from django.contrib.auth import logout
from django.shortcuts import render_to_response, redirect
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseNotFound
from django.core.context_processors import csrf
from django.db.models import Sum, Q
from django.contrib.auth.models import User

from aligulac.settings import DEBUG, PATH_TO_DIR
from ratings.models import Rating, Period, Player, Team, Match, Event, Earnings
from ratings.tools import find_player, filter_active_ratings
from ratings.templatetags.ratings_extras import urlfilter

from blog.models import Post

import simplejson

from countries import transformations

def base_ctx(section=None, subpage=None, request=None, context=None):
    curp = Period.objects.filter(computed=True).order_by('-start')[0]
    menu = [('Ranking', '/periods/%i' % curp.id),\
            ('Teams', '/teams/'),\
            ('Records', '/records/'),\
            ('Results', '/results/'),\
            ('Reports', '/reports/'),\
            ('Predict', '/predict/'),\
            ('About', '/faq/'),\
            ('Submit', '/add/')]

    base = {'curp': curp, 'menu': menu, 'debug': DEBUG}

    if request != None:
        base['adm'] = request.user.is_authenticated()

    if section == 'Records':
        base['submenu'] = [('HoF', '/records/?race=hof'),\
                           ('All', '/records/?race=all'),\
                           ('Protoss', '/records/?race=P'),\
                           ('Terran', '/records/?race=T'),\
                           ('Zerg', '/records/?race=Z')]
    elif section == 'Results':
        base['submenu'] = [('By Date', '/results/'),\
                           ('By Event', '/results/events/'),\
                           ('Search', '/results/search/')]
    elif section == 'Submit' and base['adm']:
        base['submenu'] = [('Matches', '/add/'),\
                           ('Review', '/add/review/'),\
                           ('Events', '/add/events/'),\
                           ('Integrity', '/add/integrity/'),\
                           ('Misc', '/add/misc/')]
    elif section == 'Teams':
        base['submenu'] = [('Ranking', '/teams/'),\
                           ('Transfers', '/player_transfers/')]
    elif section == 'Ranking':
        base['submenu'] = [('Current', '/periods/%i' % curp.id),\
                           ('History', '/periods/'),\
                           ('Earnings', '/earnings/')]
    elif section == 'About':
        base['submenu'] = [('FAQ', '/faq/'),
                           ('Blog', '/blog/'),
                           ('Database', '/db/')]
    elif section == 'Reports':
        pass

    if section != None:
        base['curpage'] = section

    if subpage != None:
        base['cursubpage'] = subpage

    if context != None:
        if type(context) == Player:
            rating = Rating.objects.filter(player=context, comp_rat__isnull=False).order_by('-period')
            earnings = Earnings.objects.filter(player=context)

            base_url = '/players/%i-%s/' % (context.id, urlfilter(context.tag))

            base['submenu'] += [None, ('%s:' % context.tag, base_url)]

            if rating.exists():
                base['submenu'].append(('Rating history', base_url + 'historical/'))

            base['submenu'].append(('Match history', base_url + 'results/'))
            
            if earnings.exists():
                base['submenu'].append(('Earnings', base_url + 'earnings/'))

            if rating.exists():
                base['submenu'].append(('Adjustments', base_url + 'period/%i' % rating[0].period.id))

    return base

def db(request):
    base = base_ctx('About', 'Database', request)

    ngames = Match.objects.all().aggregate(Sum('sca'))['sca__sum'] + Match.objects.all().aggregate(Sum('scb'))['scb__sum']
    nmatches = Match.objects.all().count()
    nuntreated = Match.objects.filter(treated=False).count()

    nwol = Match.objects.filter(game='WoL').count()
    nhots = Match.objects.filter(game='HotS').count()
    
    nonline = Match.objects.filter(offline = False).count()
    noffline = Match.objects.filter(offline = True).count()

    npartial = Match.objects.exclude(eventobj__isnull=True, event='').count()
    nfull = Match.objects.filter(eventobj__isnull=False).count()
    nuncatalogued = Match.objects.filter(eventobj__isnull=True).count()

    nplayers = Player.objects.all().count()
    nkoreans = Player.objects.filter(country='KR').count()
    nteams = Team.objects.all().count()
    nactive = Team.objects.filter(active=True).count()
    ninactive = Team.objects.filter(active=False).count()

    base.update({'ngames': ngames, 'nmatches': nmatches, 'nuntreated': nuntreated,\
                 'nwol': nwol, 'nhots': nhots, 'nonline': nonline, 'noffline': noffline,\
                 'npartial': npartial, 'nfull': nfull, 'nuncatalogued': nuncatalogued,\
                 'nplayers': nplayers, 'nkoreans': nkoreans,\
                 'nteams': nteams, 'nactive': nactive, 'ninactive': ninactive})

    submitters = []
    for u in User.objects.all():
        n = Match.objects.filter(submitter=u).count()
        if n > 0:
            submitters.append((u, n))
    submitters.sort(key=lambda t: t[1], reverse=True)
    base['submitters'] = submitters

    dumpfile = '/usr/local/www/media/al/aligulac.sql'
    base['dump'] = os.path.exists(dumpfile)
    if base['dump']:
        stat = os.stat(dumpfile)
        base['megabytes'] = float(stat.st_size)/1048576
        base['modified'] = datetime.fromtimestamp(stat.st_mtime)

    base['updated'] = datetime.fromtimestamp(os.stat(PATH_TO_DIR + 'update').st_mtime)

    return render_to_response('db.html', base)

def home(request):
    base = base_ctx(request=request)

    period = Period.objects.filter(computed=True).order_by('-start')[0]
    entries = filter_active_ratings(Rating.objects.filter(period=period).order_by('-rating'))
    entries = entries.select_related('team', 'teammembership')[0:10]
    for entry in entries:
        teams = entry.player.teammembership_set.filter(current=True)
        if teams.exists():
            entry.team = teams[0].team.shortname
            entry.teamfull = teams[0].team.name
            entry.teamid = teams[0].team.id

    blogs = Post.objects.order_by('-date')[0:3]

    base.update({'entries': entries, 'blogposts': blogs})
    
    return render_to_response('index.html', base)

def search(request, q=''):
    base = base_ctx(request=request)

    if q == '':
        q = request.GET['q']

    players = find_player(q.split(' '), make=False, soft=True)

    teams = Team.objects.all()
    for qpart in q.split(' '):
        if qpart.strip() == '':
            continue
        query = Q(name__icontains=qpart) | Q(alias__name__icontains=q)
        teams = teams.filter(query)
    teams = teams.distinct()

    events = Event.objects.filter(type__in=['category','event'])
    for qpart in q.split(' '):
        if qpart.strip() == '':
            continue
        events = events.filter(Q(fullname__icontains=qpart))
    events = events.order_by('lft')

    if players.count() == 1 and teams.count() == 0 and events.count() == 0:
        return redirect('/players/%i-%s/' % (players[0].id, urlfilter(players[0].tag)))
    elif players.count() == 0 and teams.count() == 1 and events.count() == 0:
        return redirect('/teams/%i-%s/' % (teams[0].id, urlfilter(teams[0].name)))
    elif players.count() == 0 and teams.count() == 0 and events.count() == 1:
        return redirect('/results/events/%i-%s/' % (events[0].id, urlfilter(events[0].fullname)))

    base.update({'players': players, 'query': q, 'teams': teams, 'events': events})

    return render_to_response('search.html', base)

def api_search(request, q=''):
    if q == '':
        q = request.GET['q']

    players = Player.objects.filter(tag__icontains=q)
    d = []
    for p in players:
        dp = {'tag': p.tag, 'race': p.race}
        if p.country != None and p.country != '':
            dp['country'] = transformations.cc_to_cn(p.country)

        try:
            r = Rating.objects.filter(player=p).order_by('-period__id')[0]
            dp['rating'] = r.rating
            dp['rating_vp'] = r.rating_vp
            dp['rating_vt'] = r.rating_vt
            dp['rating_vz'] = r.rating_vz
            dp['dev'] = r.dev
            dp['dev_vp'] = r.dev_vp
            dp['dev_vt'] = r.dev_vt
            dp['dev_vz'] = r.dev_vz
        except:
            dp['rating'] = 0
            dp['rating_vp'] = 0
            dp['rating_vt'] = 0
            dp['rating_vz'] = 0
            dp['dev'] = 0.6
            dp['dev_vp'] = 0.6
            dp['dev_vt'] = 0.6
            dp['dev_vz'] = 0.6

        d.append(dp)

    return HttpResponse(simplejson.dumps(d), mimetype='application/json')

def logoutv(request):
    logout(request)
    return redirect('/add/')

def loginv(request):
    base = base_ctx(request=request)
    base.update(csrf(request))
    return render_to_response('login.html', base)

def changepwd(request):
    base = base_ctx(request=request)

    if not request.user.is_authenticated():
        base.update(csrf(request))
        return render_to_response('login.html', base)

    base.update({'user': request.user.username})

    if not ('old' in request.POST and 'new' in request.POST and 'newre' in request.POST):
        base.update(csrf(request))
        return render_to_response('changepwd.html', base)

    if not request.user.check_password(request.POST['old']):
        base.update({'wrong_old': True})
        base.update(csrf(request))
        return render_to_response('changepwd.html', base)
    
    if request.POST['new'] != request.POST['newre']:
        base.update({'no_match': True})
        base.update(csrf(request))
        return render_to_response('changepwd.html', base)

    request.user.set_password(request.POST['new'])
    request.user.save()

    return redirect('/add/')

def h404(request):
    base = base_ctx(request=request)

    return HttpResponseNotFound(render_to_string('404.html', base))

def h500(request):
    base = base_ctx(request=request)

    return HttpResponseNotFound(render_to_string('500.html', base))
