# scores/models.py
from django.db import models

TEAM_CHOICES = [
    ('own', 'Own Team'),
    ('opp', 'Opposing Team'),
]

class Game(models.Model):
    date = models.DateField()
    opponent = models.CharField(max_length=100)
    location = models.CharField(max_length=100)
    game_type = models.CharField(max_length=50, help_text="E.g., 'pub league', 'friendly'")
    cycles_per_round = models.PositiveIntegerField(default=3)
    # Map the team_first field to the existing database column "first_team"
    team_first = models.BooleanField(default=True, help_text="Does your team start first?", db_column="first_team")

    def __str__(self):
        return f"{self.date} vs {self.opponent}"


class Player(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class GamePlayer(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="game_players")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    round_number = models.PositiveIntegerField()
    team = models.CharField(max_length=4, choices=TEAM_CHOICES)

    def __str__(self):
        return f"{self.player.name} ({self.get_team_display()}) - Round {self.round_number}"


class Score(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="scores")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    round_number = models.PositiveIntegerField()
    cycle_number = models.PositiveIntegerField()
    # If your DB columns use underscores, map them:
    roll1 = models.PositiveIntegerField(blank=True, null=True, db_column="roll_1")
    roll2 = models.PositiveIntegerField(blank=True, null=True, db_column="roll_2")
    roll3 = models.PositiveIntegerField(blank=True, null=True, db_column="roll_3")
    total = models.PositiveIntegerField(default=0)
    is_strike = models.BooleanField(default=False)
    is_spare = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.player.name} - R{self.round_number}C{self.cycle_number}"
    