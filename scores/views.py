import json
from django.shortcuts import render, redirect, get_object_or_404
# Add Case and When here
from django.db.models import Sum, Max, Min, Count, F, FloatField, ExpressionWrapper, Case, When, Value, Q, Avg
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.urls import reverse
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST

from .models import Game, Player, GamePlayer, Score, Opponent, Location
from .forms import (
    GameSetupForm,
    ScoreForm,
    GamePlayerFormSet,
    PlayerForm,
    RoundOptionsForm
)
# --- Helper function for Game State ---
def get_game_state(game, current_round, request):
    # (Your existing logic - should correctly return round_complete=True when appropriate)
    own_team = list(game.game_players.filter(round_number=current_round, team="own").order_by("id"))
    opp_team = list(game.game_players.filter(round_number=current_round, team="opp").order_by("id"))
    round_team_first_key = f"round_{current_round}_team_first"
    round_team_first = request.session.get(round_team_first_key, request.session.get("round_team_first", "own"))
    scoring_order = []
    # ... (logic to build scoring_order) ...
    if round_team_first == "own":
        for i in range(max(len(own_team), len(opp_team))):
            if i < len(own_team): scoring_order.append(own_team[i])
            if i < len(opp_team): scoring_order.append(opp_team[i])
    else:
        for i in range(max(len(own_team), len(opp_team))):
            if i < len(opp_team): scoring_order.append(opp_team[i])
            if i < len(own_team): scoring_order.append(own_team[i])

    total_turns = len(scoring_order)
    if total_turns == 0: return {"message": f"Set up teams for Round {current_round}.", "current_player": None, "current_player_obj": None, "current_cycle": 1, "plus_minus": 0, "scores_data": [], "scores_qs": Score.objects.none(), "round_complete": False, "error": "No players found..."}
    scores_entered = Score.objects.filter(game=game, round_number=current_round).count()
    cycles_per_round = game.cycles_per_round if game.cycles_per_round > 0 else 1
    current_cycle = (scores_entered // total_turns) + 1
    next_index = scores_entered % total_turns
    message = ""; current_player = None; current_player_obj = None; round_complete = False
    if current_cycle > cycles_per_round:
        message = f"Round {current_round} Complete!"; round_complete = True
    elif next_index < len(scoring_order):
        current_player_obj = scoring_order[next_index]; current_player = current_player_obj.player
        message = f"Enter score for {current_player.name} (Cycle {current_cycle} of Round {current_round})"
    else: message = "Error determining next player."
    own_team_ids = [gp.player.id for gp in own_team]; opp_team_ids = [gp.player.id for gp in opp_team]
    own_total = Score.objects.filter(game=game, round_number=current_round, player__in=own_team_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
    opp_total = Score.objects.filter(game=game, round_number=current_round, player__in=opp_team_ids).aggregate(total=Coalesce(Sum("total"), 0))["total"]
    plus_minus = own_total - opp_total
    scores_qs = game.scores.filter(round_number=current_round).order_by("cycle_number", "id")
    scores_data = list(scores_qs.values('player__name', 'cycle_number', 'roll1', 'roll2', 'roll3', 'total', 'id'))
    return {"message": message, "current_player": current_player, "current_player_obj": current_player_obj, "current_cycle": current_cycle, "plus_minus": plus_minus, "scores_data": scores_data, "scores_qs": scores_qs, "round_complete": round_complete, "error": None}

    return {
        "message": message,
        "current_player": current_player, # The Player instance
        "current_player_obj": current_player_obj, # The GamePlayer instance (needed to get player on POST)
        "current_cycle": current_cycle,
        "plus_minus": plus_minus,
        "scores_data": scores_data, # Use the serializable list
        "scores_qs": scores_qs, # Keep queryset for template context (initial load)
        "round_complete": round_complete,
        "error": None # Or set an error message if needed
    }
# --- End Helper Function ---


@staff_member_required
def start_game(request):
    if request.method == "POST":
        # --- POST request handling (unchanged) ---
        form = GameSetupForm(request.POST)
        if form.is_valid():
            game = form.save()
            # Use game-specific session keys
            request.session[f"game_{game.id}_current_round"] = 1
            # Clear previous team first settings if any
            request.session.pop("round_team_first", None) # Clear old general key
            for i in range(1, 10): # Clear potential old round-specific keys
                request.session.pop(f"round_{i}_team_first", None)
            return redirect("live_game", game_id=game.id)
        # If form is invalid on POST, it will fall through and re-render below
        # including the forced evaluation.

    else: # --- GET request handling ---
        form = GameSetupForm()

    # --- FORCE QUERYSET EVALUATION for Choice Fields BEFORE rendering ---
    # Accessing the choices or iterating forces the database query to complete now,
    # preventing potential cursor issues during template rendering, especially with poolers.
    # We assign to dummy variables '_' as we don't need the results here.
    try:
        _ = list(form.fields['opponent'].queryset)
        _ = list(form.fields['location'].queryset)
        _ = list(form.fields['game_type'].queryset)
    except Exception as e:
        # Handle potential errors during queryset evaluation (e.g., DB connection)
        # You might want to log this error or add a message
        print(f"Error evaluating form querysets in start_game view: {e}")
        # Optionally add an error message to the context or raise an error
        # For now, we'll let it proceed, but the dropdowns might be empty/fail
        pass
    # --- END FORCE EVALUATION ---

    # Pass the *same* form instance (which now has cached choices) to the template
    return render(request, "scores/start_game.html", {"form": form})


@staff_member_required
def live_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    current_round_session_key = f"game_{game_id}_current_round"
    current_round = request.session.get(current_round_session_key, 1)
    if not isinstance(current_round, int): current_round = 1
    # (Round sync logic...)
    latest_score_round = Score.objects.filter(game=game).aggregate(Max("round_number"))["round_number__max"] or 0
    latest_player_round = GamePlayer.objects.filter(game=game).aggregate(Max("round_number"))["round_number__max"] or 0
    latest_round_in_db = max(latest_score_round, latest_player_round, 0)
    if latest_round_in_db > 0 and latest_round_in_db > current_round:
        current_round = latest_round_in_db; request.session[current_round_session_key] = current_round
        print(f"Updated session round to {current_round} based on DB data.")
    elif latest_round_in_db > 0 and current_round == 1 and latest_player_round >= 1:
         current_round = latest_round_in_db; request.session[current_round_session_key] = current_round
         print(f"Synced session round to {current_round} during load.")
    print(f"Live Game View - Game ID: {game_id}, Current Round: {current_round}")

    # --- Player Selection Logic ---
    if not game.game_players.filter(round_number=current_round, team="own").exists():
        # (Your existing player selection logic - POST and GET handlers)
        if request.method == "POST" and "select_players" in request.POST:
            formset = GamePlayerFormSet(request.POST, queryset=GamePlayer.objects.none(), prefix='player')
            round_options_form = RoundOptionsForm(request.POST)
            if formset.is_valid() and round_options_form.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    if instance.player: instance.game = game; instance.round_number = current_round; instance.team = "own"; instance.save()
                own_team_players = game.game_players.filter(round_number=current_round, team="own").order_by("id")
                for own_gp in own_team_players:
                    opp_player_name = f"Opp. {own_gp.player.name}"
                    if not game.game_players.filter(round_number=current_round, team="opp", player__name=opp_player_name).exists():
                        opp_player, created = Player.objects.get_or_create(name=opp_player_name)
                        GamePlayer.objects.create(game=game, player=opp_player, round_number=current_round, team="opp")
                request.session[f"round_{current_round}_team_first"] = round_options_form.cleaned_data["team_first_round"]
                request.session[current_round_session_key] = current_round
                return redirect("live_game", game_id=game.id)
            else:
                return render(request, "scores/select_players.html", {"formset": formset, "round_options_form": round_options_form, "game": game, "current_round": current_round})
        else:
            formset = GamePlayerFormSet(queryset=GamePlayer.objects.none(), prefix='player')
            round_options_form = RoundOptionsForm(initial={'team_first_round': request.session.get(f"round_{current_round}_team_first", "own")})
            return render(request, "scores/select_players.html", {"formset": formset, "round_options_form": round_options_form, "game": game, "current_round": current_round})
    # --- End Player Selection ---


    # --- AJAX Score Submission ---
    if request.method == "POST" and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        state = get_game_state(game, current_round, request)
        current_player_obj = state.get("current_player_obj")

        # Check if round already complete *before* this submission
        if state["round_complete"]:
             already_complete_url = None
             try:
                 already_complete_url = reverse("round_complete", args=[game.id])
             except NoReverseMatch as e: print(f"ERROR (AJAX - Already Complete): Failed reverse: {e}")
             except Exception as e: print(f"ERROR (AJAX - Already Complete): Unexpected URL error: {e}")
             return JsonResponse({"success": False, "error": "Round already complete.", "round_complete": True, "round_complete_url": already_complete_url }, status=400)

        if not current_player_obj:
             return JsonResponse({"success": False, "error": "Could not determine current player."}, status=400)

        score_form = ScoreForm(request.POST)
        if score_form.is_valid():
            try:
                score = score_form.save(commit=False)
                # (Assign game, player, round, cycle, calculate total)
                score.game = game; score.player = current_player_obj.player; score.round_number = current_round; score.cycle_number = state["current_cycle"]
                score.total = (score.roll1 or 0) + (score.roll2 or 0) + (score.roll3 or 0)
                score.save()

                # Get new state AFTER saving
                new_state = get_game_state(game, current_round, request)
                is_complete_now = new_state["round_complete"] # Check if *this score* completed it
                completion_url = None # Reset for this response

                if is_complete_now:
                    try:
                        completion_url = reverse("round_complete", args=[game.id])
                        print(f"DEBUG AJAX: Round COMPLETE. URL='{completion_url}'") # DEBUG
                    except NoReverseMatch as e: print(f"ERROR (AJAX - Just Completed): Failed reverse: {e}")
                    except Exception as e: print(f"ERROR (AJAX - Just Completed): Unexpected URL error: {e}")
                else:
                     print("DEBUG AJAX: Round NOT complete.") # DEBUG

                response_data = {
                    "success": True, # Score saved
                    "message": new_state["message"], "plus_minus": new_state["plus_minus"],
                    "scores": new_state["scores_data"],
                    "new_score": { 'player__name': score.player.name, 'cycle_number': score.cycle_number, 'roll1': score.roll1, 'roll2': score.roll2, 'roll3': score.roll3, 'total': score.total, 'id': score.id },
                    "round_complete": is_complete_now,
                    "round_complete_url": completion_url, # Pass generated URL (or None)
                }
                return JsonResponse(response_data)

            except Exception as e:
                 print(f"Error processing score submission: {e}")
                 return JsonResponse({"success": False, "error": "Error processing score data."}, status=500)
        else: # Form invalid
            errors = score_form.errors.as_json(); return JsonResponse({"success": False, "errors": json.loads(errors)}, status=400)

    # --- Initial Page Load (GET) ---
    state = get_game_state(game, current_round, request)
    score_form = ScoreForm()
    is_complete_initial = state["round_complete"]
    url_initial = None

    if is_complete_initial: # Try generating URL if already complete on load
        try:
            url_initial = reverse("round_complete", args=[game.id])
            print(f"DEBUG Initial Render: Round COMPLETE. URL='{url_initial}'") # DEBUG
        except NoReverseMatch as e: print(f"ERROR (Initial Render): Failed reverse: {e}")
        except Exception as e: print(f"ERROR (Initial Render): Unexpected URL error: {e}")
    else:
        print("DEBUG Initial Render: Round NOT complete.") # DEBUG

    context = {
        "game": game, "current_round": current_round, "score_form": score_form,
        "message": state["message"], "scores": state["scores_qs"], "plus_minus": state["plus_minus"],
        "round_complete": is_complete_initial, # Pass completion flag
        "round_complete_url": url_initial,     # Pass URL (might be None)
        "error": state["error"]
    }
    return render(request, "scores/live_game.html", context)


@staff_member_required
def round_complete(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    current_round_session_key = f"game_{game_id}_current_round"
    # Determine the round that was just completed from the session
    completed_round = request.session.get(current_round_session_key, 1) # Default needed? Maybe raise error if not set?

    if request.method == "POST":
        if "next_round" in request.POST:
            next_round_num = completed_round + 1
            # Optional: Add check against game.total_rounds if applicable
            # if next_round_num > game.total_rounds:
            #     # Handle game end scenario differently?
            #     return redirect("game_statistics", game_id=game.id)

            request.session[current_round_session_key] = next_round_num
            request.session.pop(f"round_{next_round_num}_team_first", None) # Clear team order for new round
            print(f"Advancing game {game_id} to round {next_round_num}")
            return redirect('live_game', game_id=game.id) # Go to live game for the new round

        elif "end_game" in request.POST:
            print(f"Ending game {game_id} after round {completed_round}.")
            # Optional: Clear game-specific session data here if desired
            # request.session.pop(current_round_session_key, None)
            # ... clear other related keys ...
            return redirect("game_statistics", game_id=game.id) # Go to stats page

    # Context needed for the simple template: just the game object
    context = {
        "game": game,
        "completed_round": completed_round # Pass for potential display if template changes later
    }
    # Render using your specific template name if different, otherwise default path is fine.
    return render(request, "scores/round_complete.html", context)
@staff_member_required
def add_player(request):
    if request.method == "POST":
        form = PlayerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("add_player") # Redirect to clear form
    else:
        form = PlayerForm()
    # Exclude auto-generated opponent players from the list displayed
    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    return render(request, "scores/add_player.html", {"form": form, "players": players})


# --- Game Statistics View (Unchanged from your provided code) ---
def game_statistics(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    # Cycle totals
    cycle_totals = Score.objects.filter(game=game)\
        .values("cycle_number")\
        .annotate(cycle_total=Sum("total"))\
        .order_by("cycle_number")

    # Round totals
    round_totals = Score.objects.filter(game=game)\
        .values("round_number")\
        .annotate(round_total=Sum("total"))\
        .order_by("round_number")

    # Overall team totals using game_players records (more robust if players change)
    # Get all player IDs associated with the game for each team across all rounds
    own_ids = list(GamePlayer.objects.filter(game=game, team="own").values_list("player_id", flat=True).distinct())
    opp_ids = list(GamePlayer.objects.filter(game=game, team="opp").values_list("player_id", flat=True).distinct())

    own_total = Score.objects.filter(game=game, player__in=own_ids)\
        .aggregate(total=Coalesce(Sum("total"), 0))["total"]
    opp_total = Score.objects.filter(game=game, player__in=opp_ids)\
        .aggregate(total=Coalesce(Sum("total"), 0))["total"]

    # Overall game result with color-coding
    if own_total > opp_total:
        overall_result = {"result": "Win", "color": "green"}
    elif own_total < opp_total:
        overall_result = {"result": "Loss", "color": "red"}
    else:
        overall_result = {"result": "Draw", "color": "gray"}

    # Detailed player stats: compute total, count of score entries (cycles), and average per cycle.
    player_stats = Score.objects.filter(game=game)\
        .values("player__id", "player__name")\
        .annotate(
            total_score=Coalesce(Sum("total"), 0),
            num_cycles=Count("id")
        ).annotate(
            # Handle potential division by zero if num_cycles is 0 (though unlikely if they have scores)
            average=ExpressionWrapper(
                Case(
                    When(num_cycles=0, then=Value(0.0)),
                    default=F("total_score") * 1.0 / F("num_cycles"), # Ensure float division
                    output_field=FloatField()
                ),
                output_field=FloatField()
            )
        ).order_by("-total_score")

    # Determine highest scorer(s) by player ID
    highest_total = player_stats.aggregate(max_total=Max("total_score"))["max_total"] or 0
    highest_scorers = [p["player__id"] for p in player_stats if p["total_score"] == highest_total] if highest_total > 0 else []

    # For the "Player Totals (Team Comparison)" table:
    # Calculate totals per player, grouping by player
    all_player_totals = Score.objects.filter(game=game)\
        .values("player__id", "player__name")\
        .annotate(player_total=Coalesce(Sum("total"), 0))\
        .order_by("player__name") # Order consistently

    # Separate into own and opp based on the distinct lists derived earlier
    own_totals_dict = {p['player__id']: p for p in all_player_totals if p['player__id'] in own_ids}
    opp_totals_dict = {p['player__id']: p for p in all_player_totals if p['player__id'] in opp_ids}

    # Create pairs based on "Opp. Player Name" convention
    zipped_totals = []
    processed_opp_ids = set()
    for own_id in own_ids:
        own_player_data = own_totals_dict.get(own_id)
        if not own_player_data: continue # Should exist, but safety check

        own_name = own_player_data['player__name']
        expected_opp_name = f"Opp. {own_name}"

        # Find the corresponding opponent
        opp_player_data = None
        for opp_id, opp_data in opp_totals_dict.items():
             if opp_data['player__name'] == expected_opp_name:
                 opp_player_data = opp_data
                 processed_opp_ids.add(opp_id) # Mark as processed
                 break

        zipped_totals.append({
            "own": own_player_data,
            "opp": opp_player_data # Will be None if no matching Opp. player found
        })

    # Add any remaining opp players that weren't matched (e.g., if naming convention failed or different numbers of players)
    for opp_id, opp_data in opp_totals_dict.items():
        if opp_id not in processed_opp_ids:
             zipped_totals.append({
                 "own": None, # No corresponding own player based on name match
                 "opp": opp_data
             })


    # Score differentials per round (Max score - Min score in that round) - This seems less useful than team diff per round.
    # Let's calculate Own Total vs Opp Total per round instead.
    round_diffs = []
    max_round = game.scores.aggregate(Max("round_number"))["round_number__max"] or 0
    for r in range(1, max_round + 1):
        own_round_ids = list(GamePlayer.objects.filter(game=game, team="own", round_number=r).values_list("player_id", flat=True))
        opp_round_ids = list(GamePlayer.objects.filter(game=game, team="opp", round_number=r).values_list("player_id", flat=True))

        own_round_total = Score.objects.filter(game=game, round_number=r, player__in=own_round_ids).aggregate(total=Coalesce(Sum("total"),0))['total']
        opp_round_total = Score.objects.filter(game=game, round_number=r, player__in=opp_round_ids).aggregate(total=Coalesce(Sum("total"),0))['total']
        round_diffs.append({
            "round_number": r,
            "own_total": own_round_total,
            "opp_total": opp_round_total,
            "differential": own_round_total - opp_round_total
        })

    context = {
        "game": game,
        "cycle_totals": cycle_totals, # Aggregated across all rounds
        "round_totals": round_totals, # Aggregated across all players
        "own_total": own_total, # Overall game total
        "opp_total": opp_total, # Overall game total
        "overall_result": overall_result,
        "player_stats": player_stats, # Overall per player
        "highest_scorers": highest_scorers,
        # "score_diff": score_diff, # Replaced this
        "round_diffs": round_diffs, # Per-round team differential
        "zipped_totals": zipped_totals, # Paired player totals
    }
    return render(request, "scores/game_stats.html", context)

# --- Past Games View (Minor adjustment for clarity) ---
def past_games(request):
    games = Game.objects.all().order_by("-date", "-id") # Add secondary sort for consistency
    past_games_data = []
    for game in games:
        # Use the more robust method from game_statistics for totals
        own_ids = list(GamePlayer.objects.filter(game=game, team="own").values_list("player_id", flat=True).distinct())
        opp_ids = list(GamePlayer.objects.filter(game=game, team="opp").values_list("player_id", flat=True).distinct())

        own_total = Score.objects.filter(game=game, player__in=own_ids)\
            .aggregate(total=Coalesce(Sum("total"), 0))["total"]
        opp_total = Score.objects.filter(game=game, player__in=opp_ids)\
            .aggregate(total=Coalesce(Sum("total"), 0))["total"]

        if own_total > opp_total:
            result = "Win"
        elif own_total < opp_total:
            result = "Loss"
        else:
            result = "Draw"
        past_games_data.append({
            "game": game,
            "result": result,
            "own_total": own_total,
            "opp_total": opp_total,
        })
    return render(request, "scores/past_games.html", {"past_games": past_games_data})

# --- Delete Game View (Unchanged) ---
@staff_member_required
def delete_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    if request.method == "POST":
        game_name = game.name # Get name before deleting for message/log if needed
        game.delete()
        print(f"Deleted game: {game_name} (ID: {game_id})")
        # Add a success message?
        # from django.contrib import messages
        # messages.success(request, f"Game '{game_name}' deleted successfully.")
        return redirect("past_games")  # Redirect after deletion
    return render(request, "scores/confirm_delete_game.html", {"game": game})

# Make sure you have a game_detail view referenced in round_complete.html if needed
# Example:
def game_detail(request, game_id):
     game = get_object_or_404(Game, id=game_id)
     # Potentially show overview, links to stats, live game etc.
     return render(request, "scores/game_detail.html", {"game": game})

def player_statistics(request):
    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    selected_player = None
    stats = {}
    chart_data_json = None # <<<<< Initialize chart_data_json to None here

    player_id = request.GET.get('player_id')

    if player_id:
        try:
            selected_player = get_object_or_404(Player, id=player_id)
            player_scores = Score.objects.filter(player=selected_player)
            player_games = GamePlayer.objects.filter(player=selected_player)

            if player_scores.exists():
                # --- Stats Calculations ---
                # ... (keep all your stat calculation logic) ...
                total_score_agg=player_scores.aggregate(total_score=Coalesce(Sum('total'),0)); stats['total_score']=total_score_agg['total_score']; stats['total_cycles']=player_scores.count(); rolls_agg=player_scores.aggregate(r1=Count('roll1'),r2=Count('roll2'),r3=Count('roll3')); stats['total_rolls']=rolls_agg['r1']+rolls_agg['r2']+rolls_agg['r3']; stats['avg_per_cycle']=(stats['total_score']/stats['total_cycles']) if stats['total_cycles']>0 else 0; stats['avg_per_roll']=(stats['total_score']/stats['total_rolls']) if stats['total_rolls']>0 else 0; stats['zero_cycle_count']=player_scores.filter(total=0).count(); zero_rolls_agg=player_scores.aggregate(z1=Count('id',filter=Q(roll1=0)),z2=Count('id',filter=Q(roll2=0)),z3=Count('id',filter=Q(roll3=0))); stats['total_zero_rolls']=zero_rolls_agg['z1']+zero_rolls_agg['z2']+zero_rolls_agg['z3']; stats['zero_roll_percentage']=(stats['total_zero_rolls']/stats['total_rolls']*100) if stats['total_rolls']>0 else 0; stats['highest_cycle_score']=player_scores.aggregate(max_c=Max('total'))['max_c']; roll_max=player_scores.aggregate(max_r1=Max('roll1'),max_r2=Max('roll2'),max_r3=Max('roll3')); stats['highest_roll_score']=max(roll_max['max_r1'] or 0,roll_max['max_r2'] or 0,roll_max['max_r3'] or 0)

                # --- Improvement Trend & Chart Data ---
                improvement_data_qs = list(player_scores.values('game__id','game__date', 'game__opponent__name', 'game__location__name').annotate(game_avg=Avg('total')).order_by('game__date'))
                stats['improvement_trend'] = improvement_data_qs

                if improvement_data_qs:
                    chart_data = {'labels': [item['game__date'].strftime('%Y-%m-%d') for item in improvement_data_qs], 'data': [float(item['game_avg']) for item in improvement_data_qs]}
                    chart_data_json = json.dumps(chart_data) # Assigned value
                    # No 'else' needed here, chart_data_json remains None if no data

            # --- Game Participation & W/L/D ---
            # ... (keep W/L/D calculation logic) ...
            distinct_game_ids=player_games.values_list('game_id',flat=True).distinct(); stats['games_participated']=len(distinct_game_ids); stats['wins']=0; stats['losses']=0; stats['draws']=0; all_games_data={g.id: g for g in Game.objects.filter(id__in=distinct_game_ids)};
            for g_id in distinct_game_ids:
                game_obj=all_games_data.get(g_id);
                if not game_obj: continue;
                game_own_ids=list(GamePlayer.objects.filter(game_id=g_id,team="own").values_list("player_id",flat=True).distinct()); game_opp_ids=list(GamePlayer.objects.filter(game_id=g_id,team="opp").values_list("player_id",flat=True).distinct()); game_own_total=Score.objects.filter(game_id=g_id,player__in=game_own_ids).aggregate(total=Coalesce(Sum("total"),0))["total"]; game_opp_total=Score.objects.filter(game_id=g_id,player__in=game_opp_ids).aggregate(total=Coalesce(Sum("total"),0))["total"]; is_own_team_player=player_games.filter(game_id=g_id,team='own').exists();
                if is_own_team_player:
                    if game_own_total>game_opp_total: stats['wins']+=1
                    elif game_own_total<game_opp_total: stats['losses']+=1
                    else: stats['draws']+=1

        except Player.DoesNotExist:
            selected_player = None
            # chart_data_json remains None (its initial value)
        except Exception as e:
            print(f"Error calculating stats for player {player_id}: {e}")
            # chart_data_json remains None (its initial value)

    # --- Context ---
    # Now chart_data_json will always have a value (either None or a JSON string)
    context = {
        'players': players,
        'selected_player': selected_player,
        'stats': stats,
        'chart_data_json': chart_data_json # Pass the value (could be None)
    }
    return render(request, 'scores/player_statistics.html', context)
# --- End Player Statistics View ---







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



# scores/views.py

import json
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Max, Min, Count, F, Q, Avg, FloatField, ExpressionWrapper, Case, When, Value
from django.db.models.functions import Coalesce
from django.contrib.admin.views.decorators import staff_member_required
# Ensure require_POST is imported if used elsewhere, but not needed for this view
# from django.views.decorators.http import require_POST
from django.http import JsonResponse # Keep if used by AJAX views

# Import all necessary models
from .models import Game, Player, GamePlayer, Score, Opponent, Location, GameType
# Import forms if needed by other views
# from .forms import (...)


# --- Keep other view functions (start_game, live_game, ajax_add_*, etc.) ---


# --- UPDATED OPPONENT STATISTICS VIEW ---
# Use login_required or staff_member_required as appropriate
# @staff_member_required
def opponent_statistics(request):
    # Data for dropdowns
    opponents = Opponent.objects.all().order_by('name')
    game_types = GameType.objects.all().order_by('name')

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

            # --- Base Query ---
            games_query = Game.objects.filter(opponent=selected_opponent)

            # --- Apply GameType Filter (if provided and valid) ---
            if game_type_id:
                try:
                    selected_game_type = GameType.objects.get(id=game_type_id)
                    games_query = games_query.filter(game_type=selected_game_type)
                except (GameType.DoesNotExist, ValueError, TypeError): # Catch potential errors
                    # Invalid ID passed, ignore filter
                    selected_game_type = None
                    game_type_id = None # Clear invalid ID

            # --- Execute Query ---
            games_vs_opponent = games_query.order_by('date').select_related('location', 'game_type')
            game_ids = list(games_vs_opponent.values_list('id', flat=True))

            # --- Check if any games match criteria ---
            if not game_ids:
                stats['error'] = "No games found matching the selected criteria."
            else:
                stats['total_games'] = len(game_ids)

                # --- Prepare data for efficient calculation ---
                all_scores_in_games = Score.objects.filter(game_id__in=game_ids).select_related('player') # Don't need game__location here
                all_game_players = GamePlayer.objects.filter(game_id__in=game_ids).select_related('player')

                # --- Initialize aggregates and lists ---
                game_results = [] # Holds per-game calculated results
                own_total_score_all_games = 0
                opp_total_score_all_games = 0
                wins = 0
                losses = 0
                draws = 0
                score_diffs_by_date = [] # For chart
                scores_by_location = {} # {loc_name: {'wins':0, ...}}

                # --- Loop through filtered games to calculate per-game stats ---
                for game in games_vs_opponent:
                    own_ids_game = list(all_game_players.filter(game=game, team='own').values_list('player_id', flat=True))
                    opp_ids_game = list(all_game_players.filter(game=game, team='opp').values_list('player_id', flat=True))

                    own_total_game = all_scores_in_games.filter(game=game, player_id__in=own_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']
                    opp_total_game = all_scores_in_games.filter(game=game, player_id__in=opp_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']

                    # Aggregate totals
                    own_total_score_all_games += own_total_game
                    opp_total_score_all_games += opp_total_game
                    score_diff = own_total_game - opp_total_game

                    # Determine result and count W/L/D
                    result = "Draw"
                    if score_diff > 0: wins += 1; result = "Win"
                    elif score_diff < 0: losses += 1; result = "Loss"
                    else: draws += 1

                    # Store results for potential later use (or remove if not needed)
                    game_results.append({
                        'game': game,
                        'own_score': own_total_game,
                        'opp_score': opp_total_game,
                        'diff': score_diff,
                        'result': result,
                    })

                    # Data for trend chart
                    score_diffs_by_date.append({'date': game.date, 'diff': score_diff})

                    # Data for location breakdown
                    loc_name = game.location.name if game.location else "Unknown Location"
                    if loc_name not in scores_by_location:
                        scores_by_location[loc_name] = {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}
                    scores_by_location[loc_name]['count'] += 1
                    scores_by_location[loc_name]['diff_sum'] += score_diff
                    if result == "Win": scores_by_location[loc_name]['wins'] += 1
                    elif result == "Loss": scores_by_location[loc_name]['losses'] += 1
                    else: scores_by_location[loc_name]['draws'] += 1

                # --- Calculate Overall Statistics ---

                # 1. Head-to-Head Record
                stats['wins'] = wins
                stats['losses'] = losses
                stats['draws'] = draws
                stats['win_percentage'] = (wins / stats['total_games'] * 100) if stats['total_games'] > 0 else 0

                # 2. Scoring Performance (Averages, High/Low)
                stats['avg_score_for'] = (own_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_against'] = (opp_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_diff'] = stats['avg_score_for'] - stats['avg_score_against']

                game_scores_for = [g['own_score'] for g in game_results]
                game_scores_against = [g['opp_score'] for g in game_results]
                stats['highest_score_for'] = max(game_scores_for) if game_scores_for else 0
                stats['lowest_score_for'] = min(game_scores_for) if game_scores_for else 0
                stats['highest_score_against'] = max(game_scores_against) if game_scores_against else 0
                stats['lowest_score_against'] = min(game_scores_against) if game_scores_against else 0

                # 3. Performance Trend Data (Chart)
                if score_diffs_by_date:
                     chart_data = {
                         'labels': [item['date'].strftime('%Y-%m-%d') for item in score_diffs_by_date],
                         'data': [item['diff'] for item in score_diffs_by_date]
                     }
                     chart_data_json = json.dumps(chart_data)

                # 4. Performance by Location
                location_stats = []
                for loc_name, data in sorted(scores_by_location.items()):
                    avg_diff_loc = (data['diff_sum'] / data['count']) if data['count'] > 0 else 0
                    location_stats.append({
                        'name': loc_name,
                        'wins': data['wins'],
                        'losses': data['losses'],
                        'draws': data['draws'],
                        'count': data['count'],
                        'avg_diff': avg_diff_loc
                    })
                stats['location_stats'] = location_stats

                # 6. Top Performing "Own" Players vs This Opponent (in these filtered games)
                own_player_ids_in_games = all_game_players.filter(game_id__in=game_ids, team='own').values_list('player_id', flat=True).distinct()

                top_players = list(all_scores_in_games.filter(
                        game_id__in=game_ids, # Scores only from filtered games
                        player_id__in=own_player_ids_in_games
                    ).values('player__name')
                     .annotate(
                        total_score_vs_opp=Coalesce(Sum('total'), 0),
                        cycle_count_vs_opp=Count('id')
                     ).annotate(
                        avg_score_vs_opp=ExpressionWrapper(
                             Case(When(cycle_count_vs_opp=0, then=Value(0.0)),
                                  default=F('total_score_vs_opp') * 1.0 / F('cycle_count_vs_opp')),
                             output_field=FloatField()
                         )
                     ).order_by('-total_score_vs_opp') # Order by total score
                )
                stats['top_players'] = top_players

        # --- Error Handling ---
        except Opponent.DoesNotExist:
            stats['error'] = "Selected opponent not found."
        except Exception as e:
            # Log the detailed error to the console/logs
            print(f"Error calculating opponent stats for ID {opponent_id}, GameType ID {game_type_id}: {e}")
            # Provide a generic message to the user
            stats['error'] = "An error occurred while calculating statistics."

    # --- Prepare Context ---
    context = {
        'opponents': opponents,             # For opponent dropdown
        'game_types': game_types,           # For game type dropdown
        'selected_opponent': selected_opponent, # The opponent object, if selected
        'selected_game_type': selected_game_type, # The game_type object, if selected
        'stats': stats,                     # Dictionary containing calculated stats or error
        'chart_data_json': chart_data_json, # Data for the trend chart
    }
    # --- Render Template ---
    return render(request, 'scores/opponent_statistics.html', context)

# ... rest of views ...
    opponents = Opponent.objects.all().order_by('name')
    selected_opponent = None
    stats = {} # Dictionary to hold all calculated stats
    chart_data_json = None # For the trend chart

    opponent_id = request.GET.get('opponent_id')

    if opponent_id:
        try:
            selected_opponent = get_object_or_404(Opponent, id=opponent_id)

            # Filter games played against this opponent
            games_vs_opponent = Game.objects.filter(opponent=selected_opponent).order_by('date')
            game_ids = list(games_vs_opponent.values_list('id', flat=True))

            if not game_ids:
                stats['error'] = "No games found against this opponent."
            else:
                stats['total_games'] = len(game_ids)

                # --- Calculate Stats ---
                game_results = []
                own_total_score_all_games = 0
                opp_total_score_all_games = 0
                wins = 0
                losses = 0
                draws = 0
                score_diffs_by_date = [] # For chart
                scores_by_location = {} # {location_name: {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}}

                # Pre-fetch scores for efficiency
                all_scores_in_games = Score.objects.filter(game_id__in=game_ids).select_related('player', 'game__location')
                # Pre-fetch game player assignments
                all_game_players = GamePlayer.objects.filter(game_id__in=game_ids).select_related('player')

                for game in games_vs_opponent.select_related('location'): # Include location here
                    # Get player IDs for this specific game
                    own_ids_game = list(all_game_players.filter(game=game, team='own').values_list('player_id', flat=True))
                    opp_ids_game = list(all_game_players.filter(game=game, team='opp').values_list('player_id', flat=True))

                    # Calculate scores for this game using pre-fetched scores
                    own_total_game = all_scores_in_games.filter(game=game, player_id__in=own_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']
                    opp_total_game = all_scores_in_games.filter(game=game, player_id__in=opp_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']

                    own_total_score_all_games += own_total_game
                    opp_total_score_all_games += opp_total_game
                    score_diff = own_total_game - opp_total_game

                    result = "Draw"
                    if score_diff > 0:
                        wins += 1
                        result = "Win"
                    elif score_diff < 0:
                        losses += 1
                        result = "Loss"
                    else:
                        draws += 1

                    game_results.append({
                        'game': game,
                        'own_score': own_total_game,
                        'opp_score': opp_total_game,
                        'diff': score_diff,
                        'result': result,
                    })

                    # Data for trend chart
                    score_diffs_by_date.append({'date': game.date, 'diff': score_diff})

                    # Data for location breakdown
                    loc_name = game.location.name if game.location else "Unknown Location"
                    if loc_name not in scores_by_location:
                        scores_by_location[loc_name] = {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}
                    scores_by_location[loc_name]['count'] += 1
                    scores_by_location[loc_name]['diff_sum'] += score_diff
                    if result == "Win": scores_by_location[loc_name]['wins'] += 1
                    elif result == "Loss": scores_by_location[loc_name]['losses'] += 1
                    else: scores_by_location[loc_name]['draws'] += 1


                # 1. Overall Head-to-Head
                stats['wins'] = wins
                stats['losses'] = losses
                stats['draws'] = draws
                stats['win_percentage'] = (wins / stats['total_games'] * 100) if stats['total_games'] > 0 else 0

                # 2. Scoring Performance
                stats['avg_score_for'] = (own_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_against'] = (opp_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_diff'] = stats['avg_score_for'] - stats['avg_score_against']

                game_scores_for = [g['own_score'] for g in game_results]
                game_scores_against = [g['opp_score'] for g in game_results]
                stats['highest_score_for'] = max(game_scores_for) if game_scores_for else 0
                stats['lowest_score_for'] = min(game_scores_for) if game_scores_for else 0
                stats['highest_score_against'] = max(game_scores_against) if game_scores_against else 0
                stats['lowest_score_against'] = min(game_scores_against) if game_scores_against else 0

                # 3. Performance Trend Data (Chart)
                if score_diffs_by_date:
                     chart_data = {
                         'labels': [item['date'].strftime('%Y-%m-%d') for item in score_diffs_by_date],
                         'data': [item['diff'] for item in score_diffs_by_date]
                     }
                     chart_data_json = json.dumps(chart_data)

                # 4. Performance by Location
                location_stats = []
                for loc_name, data in sorted(scores_by_location.items()):
                    avg_diff_loc = (data['diff_sum'] / data['count']) if data['count'] > 0 else 0
                    location_stats.append({
                        'name': loc_name,
                        'wins': data['wins'],
                        'losses': data['losses'],
                        'draws': data['draws'],
                        'count': data['count'],
                        'avg_diff': avg_diff_loc
                    })
                stats['location_stats'] = location_stats


                # 6. Top Performing "Own" Players vs This Opponent
                # Find IDs of players who played for 'own' team in these games
                own_player_ids_in_games = all_game_players.filter(game_id__in=game_ids, team='own').values_list('player_id', flat=True).distinct()

                # Aggregate scores for those players ONLY in games against this opponent
                top_players = list(all_scores_in_games.filter(
                        game_id__in=game_ids,
                        player_id__in=own_player_ids_in_games # Only 'own' team players
                    ).values('player__name') # Group by player name
                     .annotate(
                        total_score_vs_opp=Coalesce(Sum('total'), 0),
                        cycle_count_vs_opp=Count('id') # Count score entries (cycles)
                     ).annotate(
                        avg_score_vs_opp=ExpressionWrapper( # Calculate average
                             Case(When(cycle_count_vs_opp=0, then=Value(0.0)),
                                  default=F('total_score_vs_opp') * 1.0 / F('cycle_count_vs_opp')),
                             output_field=FloatField()
                         )
                     ).order_by('-total_score_vs_opp') # Order by total score descending
                )
                stats['top_players'] = top_players


        except Opponent.DoesNotExist:
            stats['error'] = "Selected opponent not found."
        except Exception as e:
            print(f"Error calculating opponent stats for ID {opponent_id}: {e}") # Log error
            stats['error'] = "An error occurred while calculating statistics."

    context = {
        'opponents': opponents,
        'selected_opponent': selected_opponent,
        'stats': stats,
        'chart_data_json': chart_data_json,
    }
    return render(request, 'scores/opponent_statistics.html', context)

    opponents = Opponent.objects.all().order_by('name')
    selected_opponent = None
    stats = {} # Dictionary to hold all calculated stats
    chart_data_json = None # For the trend chart

    opponent_id = request.GET.get('opponent_id')

    if opponent_id:
        try:
            selected_opponent = get_object_or_404(Opponent, id=opponent_id)

            # Filter games played against this opponent
            games_vs_opponent = Game.objects.filter(opponent=selected_opponent).order_by('date')
            game_ids = list(games_vs_opponent.values_list('id', flat=True))

            if not game_ids:
                stats['error'] = "No games found against this opponent."
            else:
                stats['total_games'] = len(game_ids)

                # --- Calculate Stats ---
                game_results = []
                own_total_score_all_games = 0
                opp_total_score_all_games = 0
                wins = 0
                losses = 0
                draws = 0
                score_diffs_by_date = [] # For chart
                scores_by_location = {} # {location_name: {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}}

                # Pre-fetch scores for efficiency
                all_scores_in_games = Score.objects.filter(game_id__in=game_ids).select_related('player', 'game__location')
                # Pre-fetch game player assignments
                all_game_players = GamePlayer.objects.filter(game_id__in=game_ids).select_related('player')

                for game in games_vs_opponent.select_related('location'): # Include location here
                    # Get player IDs for this specific game
                    own_ids_game = list(all_game_players.filter(game=game, team='own').values_list('player_id', flat=True))
                    opp_ids_game = list(all_game_players.filter(game=game, team='opp').values_list('player_id', flat=True))

                    # Calculate scores for this game using pre-fetched scores
                    own_total_game = all_scores_in_games.filter(game=game, player_id__in=own_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']
                    opp_total_game = all_scores_in_games.filter(game=game, player_id__in=opp_ids_game).aggregate(total=Coalesce(Sum('total'), 0))['total']

                    own_total_score_all_games += own_total_game
                    opp_total_score_all_games += opp_total_game
                    score_diff = own_total_game - opp_total_game

                    result = "Draw"
                    if score_diff > 0:
                        wins += 1
                        result = "Win"
                    elif score_diff < 0:
                        losses += 1
                        result = "Loss"
                    else:
                        draws += 1

                    game_results.append({
                        'game': game,
                        'own_score': own_total_game,
                        'opp_score': opp_total_game,
                        'diff': score_diff,
                        'result': result,
                    })

                    # Data for trend chart
                    score_diffs_by_date.append({'date': game.date, 'diff': score_diff})

                    # Data for location breakdown
                    loc_name = game.location.name if game.location else "Unknown Location"
                    if loc_name not in scores_by_location:
                        scores_by_location[loc_name] = {'wins': 0, 'losses': 0, 'draws': 0, 'diff_sum': 0, 'count': 0}
                    scores_by_location[loc_name]['count'] += 1
                    scores_by_location[loc_name]['diff_sum'] += score_diff
                    if result == "Win": scores_by_location[loc_name]['wins'] += 1
                    elif result == "Loss": scores_by_location[loc_name]['losses'] += 1
                    else: scores_by_location[loc_name]['draws'] += 1


                # 1. Overall Head-to-Head
                stats['wins'] = wins
                stats['losses'] = losses
                stats['draws'] = draws
                stats['win_percentage'] = (wins / stats['total_games'] * 100) if stats['total_games'] > 0 else 0

                # 2. Scoring Performance
                stats['avg_score_for'] = (own_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_against'] = (opp_total_score_all_games / stats['total_games']) if stats['total_games'] > 0 else 0
                stats['avg_score_diff'] = stats['avg_score_for'] - stats['avg_score_against']

                game_scores_for = [g['own_score'] for g in game_results]
                game_scores_against = [g['opp_score'] for g in game_results]
                stats['highest_score_for'] = max(game_scores_for) if game_scores_for else 0
                stats['lowest_score_for'] = min(game_scores_for) if game_scores_for else 0
                stats['highest_score_against'] = max(game_scores_against) if game_scores_against else 0
                stats['lowest_score_against'] = min(game_scores_against) if game_scores_against else 0

                # 3. Performance Trend Data (Chart)
                if score_diffs_by_date:
                     chart_data = {
                         'labels': [item['date'].strftime('%Y-%m-%d') for item in score_diffs_by_date],
                         'data': [item['diff'] for item in score_diffs_by_date]
                     }
                     chart_data_json = json.dumps(chart_data)

                # 4. Performance by Location
                location_stats = []
                for loc_name, data in sorted(scores_by_location.items()):
                    avg_diff_loc = (data['diff_sum'] / data['count']) if data['count'] > 0 else 0
                    location_stats.append({
                        'name': loc_name,
                        'wins': data['wins'],
                        'losses': data['losses'],
                        'draws': data['draws'],
                        'count': data['count'],
                        'avg_diff': avg_diff_loc
                    })
                stats['location_stats'] = location_stats


                # 6. Top Performing "Own" Players vs This Opponent
                # Find IDs of players who played for 'own' team in these games
                own_player_ids_in_games = all_game_players.filter(game_id__in=game_ids, team='own').values_list('player_id', flat=True).distinct()

                # Aggregate scores for those players ONLY in games against this opponent
                top_players = list(all_scores_in_games.filter(
                        game_id__in=game_ids,
                        player_id__in=own_player_ids_in_games # Only 'own' team players
                    ).values('player__name') # Group by player name
                     .annotate(
                        total_score_vs_opp=Coalesce(Sum('total'), 0),
                        cycle_count_vs_opp=Count('id') # Count score entries (cycles)
                     ).annotate(
                        avg_score_vs_opp=ExpressionWrapper( # Calculate average
                             Case(When(cycle_count_vs_opp=0, then=Value(0.0)),
                                  default=F('total_score_vs_opp') * 1.0 / F('cycle_count_vs_opp')),
                             output_field=FloatField()
                         )
                     ).order_by('-total_score_vs_opp') # Order by total score descending
                )
                stats['top_players'] = top_players


        except Opponent.DoesNotExist:
            stats['error'] = "Selected opponent not found."
        except Exception as e:
            print(f"Error calculating opponent stats for ID {opponent_id}: {e}") # Log error
            stats['error'] = "An error occurred while calculating statistics."

    context = {
        'opponents': opponents,
        'selected_opponent': selected_opponent,
        'stats': stats,
        'chart_data_json': chart_data_json,
    }
    return render(request, 'scores/opponent_statistics.html', context)