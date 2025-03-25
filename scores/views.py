from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Max, Min, Count, F, FloatField, ExpressionWrapper
from django.contrib.admin.views.decorators import staff_member_required
from .models import Game, Player, GamePlayer, Score
from .forms import (
    GameSetupForm, 
    ScoreForm, 
    GamePlayerFormSet, 
    PlayerForm, 
    RoundOptionsForm
)

@staff_member_required
def start_game(request):
    if request.method == "POST":
        form = GameSetupForm(request.POST)
        if form.is_valid():
            game = form.save()
            request.session["game_id"] = game.id
            request.session["current_round"] = 1  # Reset current_round for new game
            return redirect("live_game", game_id=game.id)
    else:
        form = GameSetupForm()
    return render(request, "scores/start_game.html", {"form": form})



@staff_member_required
def live_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    
    # Determine the current round dynamically
    current_round = request.session.get("current_round", 1)
    if not isinstance(current_round, int):  # Ensure it’s an integer
        current_round = 1
    latest_round = game.game_players.aggregate(Max("round_number"))["round_number__max"] or 0
    if latest_round > current_round:
        current_round = latest_round
    
    print(f"Live Game - Initial current_round: {current_round}, Latest Round: {latest_round}, Session: {request.session.get('current_round')}")  # Debug
    
    # If own team players for this round haven't been saved, show the selection formset.
    if not game.game_players.filter(round_number=current_round, team="own").exists():
        if request.method == "POST" and "select_players" in request.POST:
            formset = GamePlayerFormSet(request.POST, queryset=GamePlayer.objects.none())
            round_options_form = RoundOptionsForm(request.POST)
            if formset.is_valid() and round_options_form.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.game = game
                    instance.round_number = current_round
                    instance.team = "own"
                    instance.save()
                # Auto-generate opposing team players
                own_team = game.game_players.filter(round_number=current_round, team="own").order_by("id")
                for own in own_team:
                    if not game.game_players.filter(
                        round_number=current_round,
                        team="opp",
                        player__name=f"Opp. {own.player.name}"
                    ).exists():
                        opp_player, created = Player.objects.get_or_create(name=f"Opp. {own.player.name}")
                        GamePlayer.objects.create(
                            game=game,
                            player=opp_player,
                            round_number=current_round,
                            team="opp"
                        )
                request.session["round_team_first"] = round_options_form.cleaned_data["team_first_round"]
                return redirect("live_game", game_id=game.id)
            else:
                print(f"Live Game - POST error, current_round: {current_round}")  # Debug
                return render(request, "scores/select_players.html", {
                    "formset": formset,
                    "round_options_form": round_options_form,
                    "game": game,
                    "current_round": current_round
                })
        else:
            formset = GamePlayerFormSet(queryset=GamePlayer.objects.none())
            round_options_form = RoundOptionsForm()
            print(f"Live Game - GET, rendering with current_round: {current_round}")  # Debug
            return render(request, "scores/select_players.html", {
                "formset": formset,
                "round_options_form": round_options_form,
                "game": game,
                "current_round": current_round
            })

    # Rest of the function unchanged...
    if not game.game_players.filter(round_number=current_round, team="opp").exists():
        own_team_qs = game.game_players.filter(round_number=current_round, team="own").order_by("id")
        for own in own_team_qs:
            opp_player = Player.objects.create(name=f"Opp. {own.player.name}")
            GamePlayer.objects.create(
                game=game,
                player=opp_player,
                round_number=current_round,
                team="opp"
            )

    own_team = list(game.game_players.filter(round_number=current_round, team="own").order_by("id"))
    opp_team = list(game.game_players.filter(round_number=current_round, team="opp").order_by("id"))
    round_team_first = request.session.get("round_team_first", "own")
    scoring_order = []
    if round_team_first == "own":
        for i in range(max(len(own_team), len(opp_team))):
            if i < len(own_team):
                scoring_order.append(own_team[i])
            if i < len(opp_team):
                scoring_order.append(opp_team[i])
    else:
        for i in range(max(len(own_team), len(opp_team))):
            if i < len(opp_team):
                scoring_order.append(opp_team[i])
            if i < len(own_team):
                scoring_order.append(own_team[i])
    
    total_turns = len(scoring_order)
    scores_entered = Score.objects.filter(game=game, round_number=current_round).count()
    current_cycle = (scores_entered // total_turns) + 1
    next_index = scores_entered % total_turns

    if current_cycle > game.cycles_per_round:
        return redirect("round_complete", game_id=game.id)
    else:
        current_player = scoring_order[next_index]
        message = f"Enter score for {current_player.player.name} (Cycle {current_cycle} of Round {current_round})"

    score_submitted = False
    score_form = ScoreForm()
    if request.method == "POST" and "enter_score" in request.POST:
        score_form = ScoreForm(request.POST)
        if score_form.is_valid() and current_player is not None:
            score = score_form.save(commit=False)
            score.game = game
            score.player = current_player.player
            score.round_number = current_round
            score.cycle_number = current_cycle
            score.total = (score.roll1 or 0) + (score.roll2 or 0) + (score.roll3 or 0)
            score.save()
            score_submitted = True
            return redirect("live_game", game_id=game.id)

    own_team_ids = [gp.player.id for gp in own_team]
    opp_team_ids = [gp.player.id for gp in opp_team]
    own_total = Score.objects.filter(game=game, round_number=current_round, player__in=own_team_ids).aggregate(Sum("total"))["total__sum"] or 0
    opp_total = Score.objects.filter(game=game, round_number=current_round, player__in=opp_team_ids).aggregate(Sum("total"))["total__sum"] or 0
    plus_minus = own_total - opp_total

    scores = game.scores.filter(round_number=current_round).order_by("cycle_number", "id")
    context = {
        "game": game,
        "score_form": score_form,
        "score_submitted": score_submitted,
        "message": message,
        "scores": scores,
        "plus_minus": plus_minus,
    }
    return render(request, "scores/live_game.html", context)

@staff_member_required
def add_player(request):
    if request.method == "POST":
        form = PlayerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("add_player")
    else:
        form = PlayerForm()
    # Exclude auto‑generated opponent players from the list.
    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    return render(request, "scores/add_player.html", {"form": form, "players": players})


from django.db.models import Sum
from .models import Game, GamePlayer, Score


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
    
    # Overall team totals using game_players records
    own_ids = list(game.game_players.filter(team="own").values_list("player_id", flat=True))
    opp_ids = list(game.game_players.filter(team="opp").values_list("player_id", flat=True))
    
    own_total = Score.objects.filter(game=game, player__in=own_ids)\
        .aggregate(total=Sum("total"))["total"] or 0
    opp_total = Score.objects.filter(game=game, player__in=opp_ids)\
        .aggregate(total=Sum("total"))["total"] or 0
    
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
            total_score=Sum("total"),
            num_cycles=Count("id")
        ).annotate(
            average=ExpressionWrapper(
                F("total_score") / F("num_cycles"),
                output_field=FloatField()
            )
        ).order_by("-total_score")
    
    # Determine highest scorer(s) by player ID
    highest_total = player_stats.aggregate(max_total=Max("total_score"))["max_total"]
    highest_scorers = [p["player__id"] for p in player_stats if p["total_score"] == highest_total]
    
    # For the "Player Totals (Team Comparison)" table:
    # Compute own team totals per player.
    own_totals = Score.objects.filter(game=game, player__in=own_ids)\
        .values("player__id", "player__name")\
        .annotate(player_total=Sum("total"))\
        .order_by("player__name")
    opp_totals = Score.objects.filter(game=game, player__in=opp_ids)\
        .values("player__id", "player__name")\
        .annotate(player_total=Sum("total"))\
        .order_by("player__name")
    # Pair them using zip (assumes both querysets are in the same order).
    zipped_totals = list(zip(own_totals, opp_totals))
    
    # Score differentials per round
    score_diff = Score.objects.filter(game=game)\
        .values("round_number")\
        .annotate(
            max_score=Max("total"),
            min_score=Min("total"),
            differential=Max("total") - Min("total")
        ).order_by("round_number")
    
    context = {
        "game": game,
        "cycle_totals": cycle_totals,
        "round_totals": round_totals,
        "own_total": own_total,
        "opp_total": opp_total,
        "overall_result": overall_result,
        "player_stats": player_stats,
        "highest_scorers": highest_scorers,
        "score_diff": score_diff,
        "zipped_totals": zipped_totals,
    }
    return render(request, "scores/game_stats.html", context)


@staff_member_required
def round_complete(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    if request.method == "POST":
        if "next_round" in request.POST:
            latest_round = game.game_players.aggregate(Max("round_number"))["round_number__max"] or 1
            next_round = latest_round + 1
            request.session["current_round"] = next_round
            return redirect("live_game", game_id=game.id)
        elif "end_game" in request.POST:
            return redirect("game_statistics", game_id=game.id)
    return render(request, "scores/round_complete.html", {"game": game})

def past_games(request):
    games = Game.objects.all().order_by("-date")
    past_games_data = []
    for game in games:
        own_ids = game.game_players.filter(team="own").values_list("player_id", flat=True)
        opp_ids = game.game_players.filter(team="opp").values_list("player_id", flat=True)
        own_total = Score.objects.filter(game=game, player_id__in=own_ids).aggregate(Sum("total"))["total__sum"] or 0
        opp_total = Score.objects.filter(game=game, player_id__in=opp_ids).aggregate(Sum("total"))["total__sum"] or 0
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

@staff_member_required
def delete_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    if request.method == "POST":
        game.delete()
        return redirect("past_games")  # Redirect after deletion
    return render(request, "scores/confirm_delete_game.html", {"game": game})