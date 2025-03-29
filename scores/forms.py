# scores/forms.py
from django import forms
from django.forms import modelformset_factory
# Add Opponent to imports
from .models import Game, Score, GamePlayer, Player, Opponent, Location, GameType


class GameSetupForm(forms.ModelForm):
    # Use ModelChoiceField for opponent dropdown
    opponent = forms.ModelChoiceField(
        queryset=Opponent.objects.all().order_by('name'),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_opponent"}) # Add id for JS
    )
    # Ensure Location and GameType also use appropriate querysets if not default
    location = forms.ModelChoiceField(
        queryset=Location.objects.all().order_by('name'),
        widget=forms.Select(attrs={"class": "form-select"})
    )
    game_type = forms.ModelChoiceField(
        queryset=GameType.objects.all().order_by('name'),
        widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = Game
        # Make sure opponent is included in fields
        fields = ["date", "opponent", "location", "game_type", "cycles_per_round"] 
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            # opponent widget is defined above
            # location widget is defined above
            # game_type widget is defined above
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
            "cycles_per_round": ("Number of turns each player takes per round."),
        }

# --- Rest of your forms (PlayerForm, GamePlayerForm, etc.) remain the same ---

class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Player name"}),
        }

class GamePlayerForm(forms.ModelForm):
    class Meta:
        model = GamePlayer
        fields = ["player"]
        widgets = {
            "player": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only include players who are not auto-generated as opponents.
        self.fields["player"].queryset = Player.objects.exclude(name__startswith="Opp.")

GamePlayerFormSet = modelformset_factory(
    GamePlayer,
    form=GamePlayerForm,
    extra=4,  # Adjust as needed
    can_delete=False
)


class ScoreForm(forms.ModelForm):
    """
    Form for submitting scores for a single turn (all 3 rolls required),
    implementing Somerset Skittles validation ("Reset on Clear with Remaining Go").
    """
    # Define fields explicitly for validation control using IntegerField
    roll1 = forms.IntegerField(
        min_value=0, max_value=9, required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center', 'placeholder': 'R1', 'aria-label': 'Roll 1', 'inputmode': 'numeric', 'pattern': '[0-9]*'})
    )
    roll2 = forms.IntegerField(
        min_value=0, max_value=9, required=True,  # Changed to required=True
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center', 'placeholder': 'R2', 'aria-label': 'Roll 2', 'inputmode': 'numeric', 'pattern': '[0-9]*'})
    )
    roll3 = forms.IntegerField(
        min_value=0, max_value=9, required=True,  # Changed to required=True
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center', 'placeholder': 'R3', 'aria-label': 'Roll 3', 'inputmode': 'numeric', 'pattern': '[0-9]*'})
    )

    class Meta:
        model = Score
        fields = ['roll1', 'roll2', 'roll3'] # Only these fields are managed directly

    def clean(self):
        """
        Apply Somerset Skittles validation rules across the submitted rolls.
        Assumes all rolls for the turn are submitted simultaneously.
        """
        cleaned_data = super().clean()
        roll1 = cleaned_data.get('roll1')
        roll2 = cleaned_data.get('roll2')
        roll3 = cleaned_data.get('roll3')

        # Ensure all rolls have values
        if roll1 is None:
            self.add_error('roll1', 'Roll 1 is required (minimum 0).')
        if roll2 is None:
            self.add_error('roll2', 'Roll 2 is required (minimum 0).')
        if roll3 is None:
            self.add_error('roll3', 'Roll 3 is required (minimum 0).')
            
        # If any roll is missing, return early
        if roll1 is None or roll2 is None or roll3 is None:
            return cleaned_data

        # --- Rule: Roll 2 Validation ---
        # Determine pins standing before Roll 2, considering reset
        pins_standing_before_roll2 = 9 if roll1 == 9 else (9 - roll1) # Reset ONLY if roll1 was 9
        
        # Validate roll2 value against pins standing
        if roll2 > pins_standing_before_roll2:
            self.add_error('roll2', f"Roll 2 score ({roll2}) cannot exceed pins standing ({pins_standing_before_roll2}) based on Roll 1.")

        # --- Rule: Roll 3 Validation ---
        # Determine pins standing before Roll 3, considering resets
        pins_standing_before_roll3 = 9 # Default: Assume reset happened before R3

        reset_before_roll2 = (roll1 == 9)

        if reset_before_roll2:
            # Pins reset before R2. Did R2 clear the *new* rack?
            if roll2 < 9:
                # R2 did NOT clear the new rack, no reset before R3
                pins_standing_before_roll3 = 9 - roll2
            # Else (roll1==9 and roll2==9), pins reset again, pins_standing_before_roll3 remains 9.
        else: # No reset before R2 (roll1 < 9)
            # Did R1+R2 clear the original rack?
            cumulative_r1_r2 = roll1 + roll2
            if cumulative_r1_r2 < 9:
                # Cumulative didn't clear, no reset before R3
                pins_standing_before_roll3 = 9 - cumulative_r1_r2
            # Else (roll1 < 9 and cumulative_r1_r2 >= 9), pins WERE reset before R3, pins_standing_before_roll3 remains 9.

        # Validate roll 3 value against calculated standing pins
        if roll3 > pins_standing_before_roll3:
            self.add_error('roll3', f"Roll 3 score ({roll3}) cannot exceed pins standing ({pins_standing_before_roll3}) based on Rolls 1 & 2.")

        # Return cleaned_data. Validity is determined by whether errors were added.
        return cleaned_data

class RoundOptionsForm(forms.Form):
    team_first_round = forms.ChoiceField(
        choices=(("own", "Own Team"), ("opp", "Opposing Team")),
        widget=forms.RadioSelect,
        initial="own",
        label="Which team goes first for this round?"
    )