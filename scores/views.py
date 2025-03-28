
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Max, Min, Count, F, FloatField, ExpressionWrapper, Case, When, Value, Q, Avg, OuterRef, Exists
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.urls import reverse
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from itertools import zip_longest


# --- CORRECTED IMPORT ---
from .models import Game, Player, GamePlayer, Score, Opponent, Location, GameType # Added GameType
# --- END CORRECTION ---

from .forms import (
    GameSetupForm,
    ScoreForm,
    GamePlayerFormSet,
    PlayerForm,
    RoundOptionsForm
)
def get_game_state(game, current_round, request):
    own_team = list(
        game.game_players
        .filter(round_number=current_round, team="own")
        .select_related("player")
        .order_by("id")
    )
    opp_team = list(
        game.game_players
        .filter(round_number=current_round, team="opp")
        .select_related("player")
        .order_by("id")
    )

    round_team_first_key = f"round_{current_round}_team_first"
    round_team_first = request.session.get(round_team_first_key, request.session.get("round_team_first", "own"))

    # Interleave players based on team that goes first
    scoring_order = []
    if round_team_first == "own":
        for own, opp in zip_longest(own_team, opp_team):
            if own: scoring_order.append(own)
            if opp: scoring_order.append(opp)
    else:
        for opp, own in zip_longest(opp_team, own_team):
            if opp: scoring_order.append(opp)
            if own: scoring_order.append(own)

    total_turns = len(scoring_order)

    if total_turns == 0:
        return {
            "message": f"Set up teams for Round {current_round}.",
            "current_player": None,
            "current_player_obj": None,
            "current_cycle": 1,
            "plus_minus": 0,
            "scores_data": [],
            "scores_qs": Score.objects.none(),
            "round_complete": False,
            "error": "No players found..."
        }

    scores_entered = Score.objects.filter(game=game, round_number=current_round).count()
    cycles_per_round = max(game.cycles_per_round, 1)
    current_cycle = (scores_entered // total_turns) + 1
    next_index = scores_entered % total_turns

    if current_cycle > cycles_per_round:
        message = f"Round {current_round} Complete!"
        round_complete = True
        current_player = current_player_obj = None
    elif next_index < total_turns:
        current_player_obj = scoring_order[next_index]
        current_player = current_player_obj.player
        message = f"Enter score for {current_player.name} (Cycle {current_cycle} of Round {current_round})"
        round_complete = False
    else:
        message = "Error determining next player."
        current_player = current_player_obj = None
        round_complete = False

    own_team_ids = [gp.player.id for gp in own_team]
    opp_team_ids = [gp.player.id for gp in opp_team]

    scores_qs = game.scores.filter(round_number=current_round).select_related("player").order_by("cycle_number", "id")
    own_total = scores_qs.filter(player_id__in=own_team_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
    opp_total = scores_qs.filter(player_id__in=opp_team_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
    plus_minus = own_total - opp_total

    scores_data = list(scores_qs.values(
        'player__name', 'cycle_number', 'roll1', 'roll2', 'roll3', 'total', 'id'
    ))

    return {
        "message": message,
        "current_player": current_player,
        "current_player_obj": current_player_obj,
        "current_cycle": current_cycle,
        "plus_minus": plus_minus,
        "scores_data": scores_data,
        "scores_qs": scores_qs,
        "round_complete": round_complete,
        "error": None
    }
# --- End Optimized Helper Function ---
@staff_member_required
def start_game(request):
    form = GameSetupForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        game = form.save()

        # Initialize round-related session keys
        request.session[f"game_{game.id}_current_round"] = 1
        request.session.pop("round_team_first", None)
        for i in range(1, 10):
            request.session.pop(f"round_{i}_team_first", None)

        return redirect("live_game", game_id=game.id)

    # Proactively catch and log queryset evaluation errors (rare, but safe in dev)
    try:
        for key in ["opponent", "location", "game_type"]:
            _ = list(form.fields[key].queryset)
    except Exception as e:
        print(f"[start_game] Error evaluating form querysets: {e}")

    return render(request, "scores/start_game.html", {"form": form})


@staff_member_required
def live_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    current_round_session_key = f"game_{game_id}_current_round"
    current_round = request.session.get(current_round_session_key, 1)
    if not isinstance(current_round, int):
        current_round = 1

    # Sync current round from DB
    round_agg = Score.objects.filter(game=game).aggregate(max_score_round=Max("round_number"))
    player_agg = GamePlayer.objects.filter(game=game).aggregate(max_player_round=Max("round_number"))
    latest_round = max(round_agg["max_score_round"] or 0, player_agg["max_player_round"] or 0)

    if latest_round > current_round:
        current_round = latest_round
        request.session[current_round_session_key] = current_round
        print(f"Synced session round to {current_round} from DB")

    print(f"Live Game View - Game ID: {game_id}, Current Round: {current_round}")

    # --- Player Selection Logic ---
    if not game.game_players.filter(round_number=current_round, team="own").exists():
        if request.method == "POST" and "select_players" in request.POST:
            formset = GamePlayerFormSet(request.POST, queryset=GamePlayer.objects.none(), prefix='player')
            round_options_form = RoundOptionsForm(request.POST)
            if formset.is_valid() and round_options_form.is_valid():
                for instance in formset.save(commit=False):
                    if instance.player:
                        instance.game = game
                        instance.round_number = current_round
                        instance.team = "own"
                        instance.save()

                own_players = game.game_players.filter(round_number=current_round, team="own").select_related("player").order_by("id")
                for gp in own_players:
                    opp_name = f"Opp. {gp.player.name}"
                    if not game.game_players.filter(round_number=current_round, team="opp", player__name=opp_name).exists():
                        opp_player, _ = Player.objects.get_or_create(name=opp_name)
                        GamePlayer.objects.create(game=game, player=opp_player, round_number=current_round, team="opp")

                request.session[f"round_{current_round}_team_first"] = round_options_form.cleaned_data["team_first_round"]
                request.session[current_round_session_key] = current_round
                return redirect("live_game", game_id=game.id)
            return render(request, "scores/select_players.html", {
                "formset": formset,
                "round_options_form": round_options_form,
                "game": game,
                "current_round": current_round
            })

        formset = GamePlayerFormSet(queryset=GamePlayer.objects.none(), prefix='player')
        round_options_form = RoundOptionsForm(initial={
            'team_first_round': request.session.get(f"round_{current_round}_team_first", "own")
        })
        return render(request, "scores/select_players.html", {
            "formset": formset,
            "round_options_form": round_options_form,
            "game": game,
            "current_round": current_round
        })

    # --- AJAX Score Submission ---
    if request.method == "POST" and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        state = get_game_state(game, current_round, request)
        current_player_obj = state.get("current_player_obj")

        if state["round_complete"]:
            try:
                complete_url = reverse("round_complete", args=[game.id])
            except Exception as e:
                print(f"ERROR (AJAX - Already Complete): {e}")
                complete_url = None
            return JsonResponse({
                "success": False,
                "error": "Round already complete.",
                "round_complete": True,
                "round_complete_url": complete_url
            }, status=400)

        if not current_player_obj:
            return JsonResponse({"success": False, "error": "Could not determine current player."}, status=400)

        score_form = ScoreForm(request.POST)
        if score_form.is_valid():
            try:
                score = score_form.save(commit=False)
                score.game = game
                score.player = current_player_obj.player
                score.round_number = current_round
                score.cycle_number = state["current_cycle"]
                score.total = (score.roll1 or 0) + (score.roll2 or 0) + (score.roll3 or 0)
                score.save()

                new_state = get_game_state(game, current_round, request)
                try:
                    completion_url = reverse("round_complete", args=[game.id]) if new_state["round_complete"] else None
                except Exception as e:
                    print(f"ERROR (AJAX - Just Completed): {e}")
                    completion_url = None

                return JsonResponse({
                    "success": True,
                    "message": new_state["message"],
                    "plus_minus": new_state["plus_minus"],
                    "scores": new_state["scores_data"],
                    "new_score": {
                        'player__name': score.player.name,
                        'cycle_number': score.cycle_number,
                        'roll1': score.roll1,
                        'roll2': score.roll2,
                        'roll3': score.roll3,
                        'total': score.total,
                        'id': score.id
                    },
                    "round_complete": new_state["round_complete"],
                    "round_complete_url": completion_url
                })
            except Exception as e:
                print(f"Error processing score submission: {e}")
                return JsonResponse({"success": False, "error": "Error processing score data."}, status=500)

        return JsonResponse({
            "success": False,
            "errors": json.loads(score_form.errors.as_json())
        }, status=400)

    # --- Initial Page Load (GET) ---
    state = get_game_state(game, current_round, request)
    score_form = ScoreForm()

    try:
        complete_url = reverse("round_complete", args=[game.id]) if state["round_complete"] else None
    except Exception as e:
        print(f"ERROR (Initial Render): {e}")
        complete_url = None

    return render(request, "scores/live_game.html", {
        "game": game,
        "current_round": current_round,
        "score_form": score_form,
        "message": state["message"],
        "scores": state["scores_qs"],
        "plus_minus": state["plus_minus"],
        "round_complete": state["round_complete"],
        "round_complete_url": complete_url,
        "error": state["error"]
    })

@staff_member_required
def round_complete(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    session_key = f"game_{game_id}_current_round"
    completed_round = request.session.get(session_key, 1)

    if request.method == "POST":
        if "next_round" in request.POST:
            next_round = completed_round + 1
            request.session[session_key] = next_round
            request.session.pop(f"round_{next_round}_team_first", None)
            print(f"Advancing game {game_id} to round {next_round}")
            return redirect("live_game", game_id=game.id)

        elif "end_game" in request.POST:
            print(f"Ending game {game_id} after round {completed_round}.")
            return redirect("game_statistics", game_id=game.id)

    return render(request, "scores/round_complete.html", {
        "game": game,
        "completed_round": completed_round
    })


@staff_member_required
def add_player(request):
    form = PlayerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("add_player")

    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    return render(request, "scores/add_player.html", {
        "form": form,
        "players": players
    })



# --- Game Statistics View (Unchanged from your provided code) ---
from django.db.models import Prefetch

def game_statistics(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    scores_qs = Score.objects.filter(game=game)

    # Preload GamePlayer once to avoid repeated queries
    game_players = GamePlayer.objects.filter(game=game).select_related("player")
    own_ids = set(p.player_id for p in game_players if p.team == "own")
    opp_ids = set(p.player_id for p in game_players if p.team == "opp")

    # Precompute player score totals
    all_player_totals = scores_qs.values("player__id", "player__name") \
        .annotate(player_total=Coalesce(Sum("total"), 0)) \
        .order_by("player__name")

    own_totals_dict = {p["player__id"]: p for p in all_player_totals if p["player__id"] in own_ids}
    opp_totals_dict = {p["player__id"]: p for p in all_player_totals if p["player__id"] in opp_ids}

    # Totals
    own_total = sum(p["player_total"] for p in own_totals_dict.values())
    opp_total = sum(p["player_total"] for p in opp_totals_dict.values())

    # Result
    if own_total > opp_total:
        overall_result = {"result": "Win", "color": "green"}
    elif own_total < opp_total:
        overall_result = {"result": "Loss", "color": "red"}
    else:
        overall_result = {"result": "Draw", "color": "gray"}

    # Round & cycle totals
    round_totals = scores_qs.values("round_number").annotate(round_total=Sum("total")).order_by("round_number")
    cycle_totals = scores_qs.values("cycle_number").annotate(cycle_total=Sum("total")).order_by("cycle_number")

    # Player stats
    player_stats = scores_qs.values("player__id", "player__name") \
        .annotate(
            total_score=Coalesce(Sum("total"), 0),
            num_cycles=Count("id")
        ) \
        .annotate(
            average=Case(
                When(num_cycles=0, then=Value(0.0)),
                default=ExpressionWrapper(
                    F("total_score") * 1.0 / F("num_cycles"),
                    output_field=FloatField()
                ),
                output_field=FloatField()
            )
        ) \
        .order_by("-total_score")

    highest_total = max((p["total_score"] for p in player_stats), default=0)
    highest_scorers = [p["player__id"] for p in player_stats if p["total_score"] == highest_total]

    # Match own/opp players by name
    zipped_totals = []
    processed_opp_ids = set()

    for own_id, own_data in own_totals_dict.items():
        own_name = own_data["player__name"]
        expected_opp_name = f"Opp. {own_name}"
        matched_opp = next((v for k, v in opp_totals_dict.items() if v["player__name"] == expected_opp_name), None)
        if matched_opp:
            processed_opp_ids.add(matched_opp["player__id"])
        zipped_totals.append({"own": own_data, "opp": matched_opp})

    # Unmatched opponents
    for opp_id, opp_data in opp_totals_dict.items():
        if opp_id not in processed_opp_ids:
            zipped_totals.append({"own": None, "opp": opp_data})

    # Round differentials
    round_diffs = []
    max_round = scores_qs.aggregate(Max("round_number"))["round_number__max"] or 0

    # Prefetch GamePlayers for all rounds
    round_gameplayers = GamePlayer.objects.filter(game=game).values("player_id", "team", "round_number")
    gameplayer_map = {}
    for entry in round_gameplayers:
        key = (entry["round_number"], entry["team"])
        gameplayer_map.setdefault(key, []).append(entry["player_id"])

    for r in range(1, max_round + 1):
        own_ids_r = gameplayer_map.get((r, "own"), [])
        opp_ids_r = gameplayer_map.get((r, "opp"), [])

        own_total_r = scores_qs.filter(round_number=r, player__in=own_ids_r).aggregate(
            total=Coalesce(Sum("total"), 0)
        )["total"]
        opp_total_r = scores_qs.filter(round_number=r, player__in=opp_ids_r).aggregate(
            total=Coalesce(Sum("total"), 0)
        )["total"]

        round_diffs.append({
            "round_number": r,
            "own_total": own_total_r,
            "opp_total": opp_total_r,
            "differential": own_total_r - opp_total_r
        })

    context = {
        "game": game,
        "cycle_totals": cycle_totals,
        "round_totals": round_totals,
        "own_total": own_total,
        "opp_total": opp_total,
        "overall_result": overall_result,
        "player_stats": player_stats,
        "highest_scorers": highest_scorers,
        "round_diffs": round_diffs,
        "zipped_totals": zipped_totals,
    }
    return render(request, "scores/game_stats.html", context)

GAMES_PER_PAGE = 5
# --- Past Games View (Minor adjustment for clarity) ---
from django.template.loader import render_to_string  # Add this import at the top of your file

def past_games(request):
    try:
        opponent_id = int(request.GET.get('opponent', '').strip())
    except (ValueError, TypeError):
        opponent_id = None

    try:
        location_id = int(request.GET.get('location', '').strip())
    except (ValueError, TypeError):
        location_id = None

    result_filter = request.GET.get('result', '').strip()

    game_list = Game.objects.select_related('opponent', 'location').order_by("-date", "-id")
    if opponent_id:
        game_list = game_list.filter(opponent_id=opponent_id)
    if location_id:
        game_list = game_list.filter(location_id=location_id)

    paginator = Paginator(game_list, GAMES_PER_PAGE)
    page_number = request.GET.get("page", 1)

    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    # Preload all GamePlayer and Score data for games on current page
    game_ids = [g.id for g in page_obj.object_list]
    all_players = GamePlayer.objects.filter(game_id__in=game_ids).values('game_id', 'team', 'player_id')
    all_scores = Score.objects.filter(game_id__in=game_ids).values('game_id', 'player_id')

    scores_by_game_team = {}
    for score in all_scores:
        game_id = score['game_id']
        player_id = score['player_id']
        if game_id not in scores_by_game_team:
            scores_by_game_team[game_id] = {'own': set(), 'opp': set()}
        for player in all_players:
            if player['game_id'] == game_id and player['player_id'] == player_id:
                scores_by_game_team[game_id][player['team']].add(player_id)

    past_games_data = []
    for game in page_obj.object_list:
        own_ids = scores_by_game_team.get(game.id, {}).get('own', set())
        opp_ids = scores_by_game_team.get(game.id, {}).get('opp', set())
        own_total = Score.objects.filter(game=game, player_id__in=own_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
        opp_total = Score.objects.filter(game=game, player_id__in=opp_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
        result = "Win" if own_total > opp_total else "Loss" if own_total < opp_total else "Draw"
        past_games_data.append({"game": game, "own_total": own_total, "opp_total": opp_total, "result": result})

    if result_filter in ["Win", "Loss", "Draw"]:
        past_games_data = [g for g in past_games_data if g["result"] == result_filter]

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            html = render_to_string('scores/_past_games_table_rows.html', {'past_games': past_games_data, 'user': request.user})
            pagination_html = render_to_string('scores/_pagination_controls.html', {'page_obj': page_obj})
            return JsonResponse({'html': html, 'pagination_html': pagination_html, 'current_page': page_obj.number})
        except Exception as e:
            import traceback
            print("AJAX filter error:", traceback.format_exc())
            return JsonResponse({'error': str(e)}, status=500)

    context = {
        "past_games": past_games_data,
        "page_obj": page_obj,
        "all_opponents": Opponent.objects.all(),
        "all_locations": Location.objects.all(),
        "active_filters": {
            "opponent": str(opponent_id) if opponent_id else '',
            "location": str(location_id) if location_id else '',
            "result": result_filter,
        }
    }
    return render(request, "scores/past_games.html", context)

@require_POST
@staff_member_required
def delete_game(request, game_id):
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    game = get_object_or_404(Game, pk=game_id)

    try:
        game.delete()
        response_data = {'status': 'success', 'message': 'Game deleted successfully'}
        status_code = 200
    except Exception as e:
        response_data = {'status': 'error', 'message': str(e)}
        status_code = 500

    if is_ajax:
        return JsonResponse(response_data, status=status_code)
    return redirect('past_games')
# Example:
def game_detail(request, game_id):
    game = get_object_or_404(
        Game.objects.prefetch_related("game_players__player", "scores"),
        id=game_id
    )
    return render(request, "scores/game_detail.html", {"game": game})

# --- Constants ---
GAMES_PER_PAGE = 5 # Define how many games per page

# --- Helper Function ---
def _get_player_improvement_data(player_id):
    """Helper function to get the raw improvement data query, ordered for the table."""
    player_scores = Score.objects.filter(player_id=player_id)
    return list(
        player_scores.values(
            'game__id', 'game__date',
            'game__opponent__name', 'game__location__name'
        )
        .annotate(game_avg=Avg('total'))
        .order_by('-game__date') # Order by most recent first for table display
    )

# --- Main Statistics View ---
def player_statistics(request):
    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    selected_player = None
    stats = {}
    chart_data_json = None
    game_history_page = None
    paginator = None
    top_players_chart_json = None

    player_id = request.GET.get('player_id')

    # --- Top 5 Own Team Players Chart --- 
    # Get scores where players were specifically on the 'own' team
    top_players_data = (
        Score.objects
        .filter(
            # This exists clause ensures each score has a matching GamePlayer
            # record with the same game_id and player_id and team='own'
            Exists(
                GamePlayer.objects.filter(
                    game_id=OuterRef('game_id'),
                    player_id=OuterRef('player_id'),
                    team='own'
                )
            )
        )
        .values('player__id', 'player__name')
        .annotate(total_score=Coalesce(Sum('total'), 0))
        .order_by('-total_score')[:5]
    )

    top_players_chart_data = {
        'labels': [p['player__name'] for p in top_players_data],
        'data': [p['total_score'] for p in top_players_data],
    }
    top_players_chart_json = json.dumps(top_players_chart_data)

    if player_id:
        try:
            selected_player = get_object_or_404(Player, id=player_id)
            player_scores = Score.objects.filter(player=selected_player)
            player_games = GamePlayer.objects.filter(player=selected_player)

            if player_scores.exists():
                total_score_agg = player_scores.aggregate(total_score=Coalesce(Sum('total'), 0))
                stats['total_score'] = total_score_agg['total_score']
                stats['total_cycles'] = player_scores.count()

                rolls_agg = player_scores.aggregate(
                    r1=Count('roll1'),
                    r2=Count('roll2'),
                    r3=Count('roll3')
                )
                stats['total_rolls'] = rolls_agg['r1'] + rolls_agg['r2'] + rolls_agg['r3']

                stats['avg_per_cycle'] = (
                    stats['total_score'] / stats['total_cycles']
                    if stats['total_cycles'] > 0 else 0
                )
                stats['avg_per_roll'] = (
                    stats['total_score'] / stats['total_rolls']
                    if stats['total_rolls'] > 0 else 0
                )

                stats['zero_cycle_count'] = player_scores.filter(total=0).count()

                zero_rolls_agg = player_scores.aggregate(
                    z1=Count('id', filter=Q(roll1=0)),
                    z2=Count('id', filter=Q(roll2=0)),
                    z3=Count('id', filter=Q(roll3=0))
                )
                stats['total_zero_rolls'] = (
                    zero_rolls_agg['z1'] + zero_rolls_agg['z2'] + zero_rolls_agg['z3']
                )
                stats['zero_roll_percentage'] = (
                    stats['total_zero_rolls'] / stats['total_rolls'] * 100
                    if stats['total_rolls'] > 0 else 0
                )

                stats['highest_cycle_score'] = player_scores.aggregate(max_c=Max('total'))['max_c']

                roll_max = player_scores.aggregate(
                    max_r1=Max('roll1'),
                    max_r2=Max('roll2'),
                    max_r3=Max('roll3')
                )
                stats['highest_roll_score'] = max(
                    roll_max.get('max_r1') or 0,
                    roll_max.get('max_r2') or 0,
                    roll_max.get('max_r3') or 0
                )

                improvement_data_qs = _get_player_improvement_data(selected_player.id)

                if improvement_data_qs:
                    chart_data_list = sorted(
                        improvement_data_qs,
                        key=lambda x: x['game__date'] if x.get('game__date') else date.min
                    )

                    chart_data = {
                        'labels': [item['game__date'].strftime('%Y-%m-%d') for item in chart_data_list if item.get('game__date')],
                        'data': [float(item['game_avg']) for item in chart_data_list if item.get('game_avg') is not None]
                    }
                    chart_data_json = json.dumps(chart_data)

                if improvement_data_qs:
                    paginator = Paginator(improvement_data_qs, GAMES_PER_PAGE)
                    try:
                        game_history_page = paginator.page(1)
                    except (EmptyPage, PageNotAnInteger):
                        game_history_page = paginator.page(1) if paginator.num_pages >= 1 else paginator.page(paginator.num_pages)

            distinct_game_ids = list(player_games.values_list('game_id', flat=True).distinct())
            stats['games_participated'] = len(distinct_game_ids)
            stats['wins'] = 0
            stats['losses'] = 0
            stats['draws'] = 0

            if distinct_game_ids:
                all_games_data = {
                    g.id: g for g in Game.objects.filter(id__in=distinct_game_ids)
                }
                all_gameplayers = GamePlayer.objects.filter(game_id__in=distinct_game_ids)
                game_team_map = {'own': {}, 'opp': {}}
                for gp in all_gameplayers:
                    game_team_map.setdefault(gp.team, {}).setdefault(gp.game_id, set()).add(gp.player_id)

                score_totals = Score.objects.filter(game_id__in=distinct_game_ids) \
                    .values('game_id', 'player_id') \
                    .annotate(total=Coalesce(Sum('total'), 0))

                game_team_totals = {gid: {'own': 0, 'opp': 0} for gid in distinct_game_ids}
                for s in score_totals:
                    gid = s['game_id']
                    pid = s['player_id']
                    total = s['total']
                    if pid in game_team_map.get('own', {}).get(gid, set()):
                        game_team_totals[gid]['own'] += total
                    elif pid in game_team_map.get('opp', {}).get(gid, set()):
                        game_team_totals[gid]['opp'] += total

                for g_id in distinct_game_ids:
                    game_obj = all_games_data.get(g_id)
                    if not game_obj:
                        continue

                    is_own_team_player = selected_player.id in game_team_map.get('own', {}).get(g_id, set())

                    if is_own_team_player:
                        own_total = game_team_totals[g_id]['own']
                        opp_total = game_team_totals[g_id]['opp']
                        if own_total > opp_total:
                            stats['wins'] += 1
                        elif own_total < opp_total:
                            stats['losses'] += 1
                        else:
                            stats['draws'] += 1

        except Player.DoesNotExist:
            selected_player = None
        except Exception as e:
            print(f"Error calculating stats for player {player_id}: {e}")
            pass

    context = {
        'players': players,
        'selected_player': selected_player,
        'stats': stats,
        'chart_data_json': chart_data_json,
        'game_history_page': game_history_page,
        'paginator': paginator,
        'player_id': player_id,
        'top_players_chart_json': top_players_chart_json,
    }
    return render(request, 'scores/player_statistics.html', context)
# --- AJAX View for Game History Pagination ---
def player_game_history_page(request, player_id, page_num):
    """
    Returns JSON data for a specific page of a player's game history.
    """
    # Basic security/validation
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request type'}, status=400)

    try:
        # Ensure player exists (or return 404 handled by get_object_or_404)
        player = get_object_or_404(Player, id=player_id)

        # Get the same base data as in the main view
        improvement_data_qs = _get_player_improvement_data(player.id)
        paginator = Paginator(improvement_data_qs, GAMES_PER_PAGE)

        page_obj = paginator.get_page(page_num) # Handles invalid page numbers gracefully

        # Prepare data for JSON serialization
        game_data = []
        for game_stat in page_obj.object_list:
            # Convert date to string, handle None values gracefully
            game_date_str = game_stat['game__date'].strftime('%Y-%m-%d') if game_stat.get('game__date') else 'N/A'
            # Generate the detail URL safely
            try:
                 game_url = request.build_absolute_uri(reverse('game_statistics', args=[game_stat['game__id']]))
            except Exception: # Handle cases where reverse fails (e.g., URL pattern not found)
                 game_url = '#' # Fallback URL

            game_data.append({
                'game_id': game_stat['game__id'],
                'date': game_date_str,
                'opponent_name': game_stat.get('game__opponent__name') or 'N/A',
                'location_name': game_stat.get('game__location__name') or 'N/A',
                'game_avg': float(game_stat['game_avg']) if game_stat.get('game_avg') is not None else 0.0, # Ensure float
                'game_url': game_url
            })

        return JsonResponse({
            'games': game_data,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
        })

    except Player.DoesNotExist: # Should be caught by get_object_or_404, but good practice
        return JsonResponse({'error': 'Player not found'}, status=404)
    except Exception as e:
        # Log the error for debugging
        print(f"Error fetching game history page (Player: {player_id}, Page: {page_num}): {e}")
        return JsonResponse({'error': 'An internal server error occurred while fetching game data.'}, status=500)

@require_POST # Ensures this view only accepts POST requests
@staff_member_required # Or login_required, depending on your auth needs
def ajax_add_opponent(request):
    opponent_name = request.POST.get('name', '').strip()

    if not opponent_name:
        return JsonResponse({'success': False, 'error': 'Opponent name cannot be empty.'}, status=400)

    try:
        # Use get_or_create to handle potential duplicates gracefully
        opponent, created = Opponent.objects.get_or_create(name = opponent_name)

        if created:
            # If created, return success with new ID and name
            return JsonResponse({
                'success': True,
                'id': opponent.id,
                'name': opponent.name
            })
        else:
            # If it already existed, return an error (or you could return the existing ID/name)
            return JsonResponse({
                'success': False,
                'error': f'Opponent "{opponent_name}" already exists.'
                # Optionally, you could return the existing info:
                # 'id': opponent.id,
                # 'name': opponent.name
            }, status=400) # Use 400 Bad Request for this type of 'error'

    except Exception as e:
        # Catch any other potential errors during DB interaction
        print(f"Error creating opponent: {e}") # Log the error
        return JsonResponse({'success': False, 'error': 'Server error creating opponent.'}, status=500)

@require_POST
@staff_member_required
def ajax_add_location(request):
    location_name = request.POST.get('name', '').strip() # Get 'name' from POST

    if not location_name:
        return JsonResponse({'success': False, 'error': 'Location name cannot be empty.'}, status=400)

    try:
        # Use Location model
        location, created = Location.objects.get_or_create(name=location_name)

        if created:
            # Return location ID and name
            return JsonResponse({
                'success': True,
                'id': location.id,
                'name': location.name
            })
        else:
            # Location already existed
            return JsonResponse({
                'success': False,
                'error': f'Location "{location_name}" already exists.'
            }, status=400)

    except Exception as e:
        # Catch potential DB errors
        print(f"Error creating location: {e}") # Log the error
        return JsonResponse({'success': False, 'error': 'Server error creating location.'}, status=500)



# --- opponent_statistics (SINGLE CORRECT VERSION) ---
def opponent_statistics(request):
    # Data for dropdowns
    opponents = Opponent.objects.all().order_by('name')
    game_types = GameType.objects.all().order_by('name') # Ensure GameType is imported

    # Selected filter values
    selected_opponent = None
    selected_game_type = None
    opponent_id = request.GET.get('opponent_id')
    game_type_id = request.GET.get('game_type_id')

    # Dictionary to hold results
    stats = {}
    chart_data_json = None

    if opponent_id:
        try:
            selected_opponent = get_object_or_404(Opponent, id=opponent_id)
            games_query = Game.objects.filter(opponent=selected_opponent)

            if game_type_id:
                try:
                    selected_game_type = GameType.objects.get(id=game_type_id)
                    games_query = games_query.filter(game_type=selected_game_type)
                except (GameType.DoesNotExist, ValueError, TypeError):
                    selected_game_type = None; game_type_id = None

            games_vs_opponent = games_query.order_by('date').select_related('location', 'game_type')
            game_ids = list(games_vs_opponent.values_list('id', flat=True))

            if not game_ids:
                stats['error'] = "No games found matching the selected criteria."
            else:
                stats['total_games'] = len(game_ids)
                all_scores_in_games = Score.objects.filter(game_id__in=game_ids).select_related('player')
                all_game_players = GamePlayer.objects.filter(game_id__in=game_ids).select_related('player')
                game_results = []; own_total_score_all_games = 0; opp_total_score_all_games = 0; wins = 0; losses = 0; draws = 0; score_diffs_by_date = []; scores_by_location = {}

                for game in games_vs_opponent:
                    own_ids_game = list(all_game_players.filter(game=game, team='own').values_list('player_id', flat=True))
                    opp_ids_game = list(all_game_players.filter(game=game, team='opp').values_list('player_id', flat=True))
                    own_total_game = all_scores_in_games.filter(game=game, player_id__in=own_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']
                    opp_total_game = all_scores_in_games.filter(game=game, player_id__in=opp_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']
                    own_total_score_all_games += own_total_game; opp_total_score_all_games += opp_total_game
                    score_diff = own_total_game - opp_total_game
                    result = "Draw";
                    if score_diff > 0: wins += 1; result = "Win"
                    elif score_diff < 0: losses += 1; result = "Loss"
                    else: draws += 1
                    game_results.append({'game': game, 'own_score': own_total_game, 'opp_score': opp_total_game, 'diff': score_diff, 'result': result})
                    score_diffs_by_date.append({'date': game.date, 'diff': score_diff})
                    loc_name = game.location.name if game.location else "Unknown Location";
                    if loc_name not in scores_by_location: scores_by_location[loc_name] = {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}
                    scores_by_location[loc_name]['count'] += 1; scores_by_location[loc_name]['diff_sum'] += score_diff
                    if result == "Win": scores_by_location[loc_name]['wins'] += 1
                    elif result == "Loss": scores_by_location[loc_name]['losses'] += 1
                    else: scores_by_location[loc_name]['draws'] += 1

                stats['wins'] = wins; stats['losses'] = losses; stats['draws'] = draws
                stats['win_percentage'] = (wins / stats['total_games'] * 100) if stats['total_games'] > 0 else 0
                stats['avg_score_for'] = (own_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_against'] = (opp_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_diff'] = stats['avg_score_for'] - stats['avg_score_against']
                game_scores_for = [g['own_score'] for g in game_results]; game_scores_against = [g['opp_score'] for g in game_results]
                stats['highest_score_for'] = max(game_scores_for) if game_scores_for else 0; stats['lowest_score_for'] = min(game_scores_for) if game_scores_for else 0
                stats['highest_score_against'] = max(game_scores_against) if game_scores_against else 0; stats['lowest_score_against'] = min(game_scores_against) if game_scores_against else 0

                if score_diffs_by_date: chart_data = {'labels': [item['date'].strftime('%Y-%m-%d') for item in score_diffs_by_date], 'data': [item['diff'] for item in score_diffs_by_date]}; chart_data_json = json.dumps(chart_data)

                location_stats = [];
                for loc_name, data in sorted(scores_by_location.items()): avg_diff_loc = (data['diff_sum'] / data['count']) if data['count'] > 0 else 0; location_stats.append({'name': loc_name, 'wins': data['wins'], 'losses': data['losses'], 'draws': data['draws'], 'count': data['count'], 'avg_diff': avg_diff_loc})
                stats['location_stats'] = location_stats

                own_player_ids_in_games = all_game_players.filter(game_id__in=game_ids, team='own').values_list('player_id', flat=True).distinct()
                top_players = list(all_scores_in_games.filter(game_id__in=game_ids, player_id__in=own_player_ids_in_games).values('player__name').annotate(total_score_vs_opp=Coalesce(Sum('total'), 0), cycle_count_vs_opp=Count('id')).annotate(avg_score_vs_opp=ExpressionWrapper( Case(When(cycle_count_vs_opp=0, then=Value(0.0)), default=F('total_score_vs_opp') * 1.0 / F('cycle_count_vs_opp')), output_field=FloatField())).order_by('-total_score_vs_opp'))
                stats['top_players'] = top_players

        except Opponent.DoesNotExist: stats['error'] = "Selected opponent not found."
        except Exception as e: print(f"Error calculating opponent stats for ID {opponent_id}, GameType ID {game_type_id}: {e}"); stats['error'] = "An error occurred while calculating statistics."

    context = {
        'opponents': opponents, 'game_types': game_types,
        'selected_opponent': selected_opponent, 'selected_game_type': selected_game_type,
        'stats': stats, 'chart_data_json': chart_data_json,
    }
    return render(request, 'scores/opponent_statistics.html', context)