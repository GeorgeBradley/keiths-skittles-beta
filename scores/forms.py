# scores/forms.py
from django import forms
from django.forms import modelformset_factory
from .models import Game, Score, GamePlayer, Player

class GameSetupForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["date", "opponent", "location", "game_type", "cycles_per_round"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "opponent": forms.TextInput(attrs={"class": "form-control"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "game_type": forms.TextInput(attrs={"class": "form-control"}),
            "cycles_per_round": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "placeholder": "e.g., 4"
            }),
        }
        labels = {
            "cycles_per_round": "Cycles per Round",
        }
        help_texts = {
            "cycles_per_round": "This is the number of complete cycles. Each cycle means that every player on each team takes one turn. For example, if you have 4 players, 4 cycles equal 16 total turns per team.",
        }
class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Player name"}),
        }

# Updated GamePlayerForm: only displays the 'player' field.
class GamePlayerForm(forms.ModelForm):
    class Meta:
        model = GamePlayer
        fields = ["player"]
        widgets = {
            "player": forms.Select(attrs={"class": "form-select"}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude players whose names start with "Opp." (auto-generated opponents)
        self.fields["player"].queryset = Player.objects.exclude(name__startswith="Opp.")

# Use the updated GamePlayerForm in the formset.
GamePlayerFormSet = modelformset_factory(
    GamePlayer,
    form=GamePlayerForm,
    extra=4,  # Adjust as needed
    can_delete=False
)

class ScoreForm(forms.ModelForm):
    class Meta:
        model = Score
        fields = ["roll1", "roll2", "roll3"]
        widgets = {
            "roll1": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "roll2": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "roll3": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

# New form for round-specific options:
class RoundOptionsForm(forms.Form):
    team_first_round = forms.ChoiceField(
        choices=(("own", "Own Team"), ("opp", "Opposing Team")),
        widget=forms.RadioSelect,
        initial="own",
        label="Which team goes first for this round?"
    )
