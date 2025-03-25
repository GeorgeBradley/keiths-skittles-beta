# scores/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Max, Min
from .models import Game, Player, GamePlayer, Score
from .forms import (
    GameSetupForm, 
    ScoreForm, 
    GamePlayerFormSet, 
    PlayerForm, 
    RoundOptionsForm  # Make sure to import the new form
)
def start_game(request):
    # Create a new game
    if request.method == "POST":
        form = GameSetupForm(request.POST)
        if form.is_valid():
            game = form.save()
            request.session["game_id"] = game.id
            return redirect("live_game", game_id=game.id)
    else:
        form = GameSetupForm()
    return render(request, "scores/start_game.html", {"form": form})
    # Create a new game
    if request.method == "POST":
        form = GameSetupForm(request.POST)
        if form.is_valid():
            game = form.save()
            request.session["game_id"] = game.id
            # Redirect to the live game view (which will later display the scoring interface)
            return redirect("live_game", game_id=game.id)
    else:
        form = GameSetupForm()
    return render(request, "scores/start_game.html", {"form": form})

def live_game(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    current_round = 1  # Default round is 1 (you can later make this dynamic)

    # Branch 1: Player selection (if no own team players exist for this round)
    if not game.game_players.filter(round_number=current_round, team="own").exists():
        if request.method == "POST" and "select_players" in request.POST:
            formset = GamePlayerFormSet(request.POST, queryset=GamePlayer.objects.none())
            round_options_form = RoundOptionsForm(request.POST)
            if formset.is_valid() and round_options_form.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.game = game
                    instance.round_number = current_round  # Auto-assign round
                    instance.team = "own"  # Force team to "own"
                    instance.save()
                # Auto-generate opposing team players for each own team player.
                own_team = game.game_players.filter(round_number=current_round, team="own").order_by("id")
                for own in own_team:
                    if not game.game_players.filter(
                        round_number=current_round,
                        team="opp",
                        player__name=f"Opp. {own.player.name}"
                    ).exists():
                        opp_player = Player.objects.create(name=f"Opp. {own.player.name}")
                        GamePlayer.objects.create(
                            game=game,
                            player=opp_player,
                            round_number=current_round,
                            team="opp"
                        )
                # Save the round-specific team-first option in the session.
                request.session["round_team_first"] = round_options_form.cleaned_data["team_first_round"]
                return redirect("live_game", game_id=game.id)
            else:
                # If invalid, re-render with errors.
                return render(request, "scores/select_players.html", {
                    "formset": formset,
                    "round_options_form": round_options_form,
                    "game": game
                })
        else:
            formset = GamePlayerFormSet(queryset=GamePlayer.objects.none())
            round_options_form = RoundOptionsForm()
        return render(request, "scores/select_players.html", {
            "formset": formset,
            "round_options_form": round_options_form,
            "game": game
        })
    
    # Branch 2: Ensure opposing team players exist.
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

    # Branch 3: Scoring mode.
    own_team = list(game.game_players.filter(round_number=current_round, team="own").order_by("id"))
    opp_team = list(game.game_players.filter(round_number=current_round, team="opp").order_by("id"))

    # Determine team order based on round-specific option.
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
    # Compute plus-minus
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
def add_player(request):
    if request.method == "POST":
        form = PlayerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("add_player")
    else:
        form = PlayerForm()
    # Exclude players that are auto-generated for the opposing team.
    players = Player.objects.exclude(name__startswith="Opp.").order_by("name")
    return render(request, "scores/add_player.html", {"form": form, "players": players})
def game_statistics(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    current_round = 1  # Adjust as needed; here we assume round 1

    # Cycle totals and round totals (unchanged)
    cycle_totals = Score.objects.filter(game=game)\
        .values("cycle_number")\
        .annotate(cycle_total=Sum("total"))\
        .order_by("cycle_number")
    round_totals = Score.objects.filter(game=game)\
        .values("round_number")\
        .annotate(round_total=Sum("total"))\
        .order_by("round_number")
    
    # Retrieve own and opposing team GamePlayers in a consistent order
    own_gameplayers = list(game.game_players.filter(round_number=current_round, team="own").order_by("id"))
    opp_gameplayers = list(game.game_players.filter(round_number=current_round, team="opp").order_by("id"))
    
    # Compute totals for own team in the same order
    own_totals = []
    for gp in own_gameplayers:
        total = Score.objects.filter(game=game, round_number=current_round, player=gp.player)\
            .aggregate(Sum("total"))["total__sum"] or 0
        own_totals.append({"player_name": gp.player.name, "player_total": total})
    
    # Compute totals for opposing team in the same order
    opp_totals = []
    for gp in opp_gameplayers:
        total = Score.objects.filter(game=game, round_number=current_round, player=gp.player)\
            .aggregate(Sum("total"))["total__sum"] or 0
        opp_totals.append({"player_name": gp.player.name, "player_total": total})
    
    # Score differentials by round
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
        "own_totals": own_totals,
        "opp_totals": opp_totals,
        "score_diff": score_diff,
    }
    return render(request, "scores/game_stats.html", context)
def round_complete(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    if request.method == "POST":
        if "next_round" in request.POST:
            # Redirect to select players with the new round number
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
        # Get player IDs for own team and opposing team
        own_ids = game.game_players.filter(team="own").values_list("player_id", flat=True)
        opp_ids = game.game_players.filter(team="opp").values_list("player_id", flat=True)

        # Calculate totals for each team
        own_total = Score.objects.filter(game=game, player__in=own_ids).aggregate(Sum("total"))["total__sum"] or 0
        opp_total = Score.objects.filter(game=game, player__in=opp_ids).aggregate(Sum("total"))["total__sum"] or 0

        if own_total > opp_total:
            result = "Win"
        elif own_total < opp_total:
            result = "Loss"
        else:
            result = "Draw"

        past_games_data.append({
            "game": game,
            "own_total": own_total,
            "opp_total": opp_total,
            "result": result,
        })

    context = {"past_games": past_games_data}
    return render(request, "scores/past_games.html", context)
