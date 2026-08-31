from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import load_config
from database import Database

BOT_VERSION = "0.13.3-image-cache"
logger = logging.getLogger("scoreboard")

config = load_config()
db = Database(config.database_path)


def discord_ts(iso: str, style: str = "F") -> str:
    dt = datetime.fromisoformat(iso)
    return f"<t:{int(dt.timestamp())}:{style}>"


def format_elapsed(start_iso: str, end_iso: str) -> str:
    """Durée compacte en français, utilisée uniquement pour les résultats publics."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    total_seconds = max(0, int((end - start).total_seconds()))

    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    # Les secondes n'apportent quelque chose que pour une réponse très rapide.
    if not parts or (not days and not hours and minutes < 5):
        parts.append(f"{seconds} s")
    return " ".join(parts[:3])


def round_has_hints(round_row) -> bool:
    return all(bool(round_row[f"hint_{index}"]) for index in (1, 2, 3))


def hint_stage_for_submission(round_row, submitted_at: str) -> int:
    """Nombre d’indices déjà réellement publiés au moment de la réponse."""
    submitted = datetime.fromisoformat(submitted_at)
    stage = 0
    for index in (1, 2, 3):
        revealed_at = round_row[f"hint_{index}_revealed_at"]
        if revealed_at and datetime.fromisoformat(revealed_at) <= submitted:
            stage += 1
    return stage


def podium_points(rank: int, hint_stage: int) -> int:
    """Barème du podium : 6/5/4, 5/4/3, 4/3/2, puis 3/2/1."""
    base = (3, 2, 1)[rank]
    return base + max(0, 3 - hint_stage)


def points_for_rank(rank: int, hint_stage: int) -> int:
    """Points d'une bonne réponse : podium dynamique, puis 1 point à partir de la 4e place."""
    if rank >= 4:
        return 1
    return podium_points(rank - 1, hint_stage)


def french_rank(rank: int) -> str:
    labels = {
        1: "premier",
        2: "deuxième",
        3: "troisième",
        4: "quatrième",
        5: "cinquième",
        6: "sixième",
        7: "septième",
        8: "huitième",
        9: "neuvième",
        10: "dixième",
    }
    return labels.get(rank, f"{rank}e")


def hint_stage_label(stage: int) -> str:
    if stage == 0:
        return "avant tout indice"
    if stage == 1:
        return "après 1 indice"
    return f"après {stage} indices"


def compute_accelerated_timing(round_row, accelerated_at: datetime) -> tuple[datetime, dict[int, datetime]]:
    """Calcule la nouvelle fin et les horaires des indices encore cachés.

    La manche ne dépasse jamais sa limite initiale. Les indices restants sont
    répartis uniformément dans le temps restant, sans jamais repousser leur
    horaire normal.
    """
    original_end = datetime.fromisoformat(round_row["original_ends_at"] or round_row["ends_at"])
    effective_end = min(original_end, accelerated_at + timedelta(hours=24))

    hidden = [
        number for number in (1, 2, 3)
        if not round_row[f"hint_{number}_revealed_at"]
    ]
    schedules: dict[int, datetime] = {}
    remaining_seconds = max(0.0, (effective_end - accelerated_at).total_seconds())
    slot_seconds = remaining_seconds / (len(hidden) + 1) if hidden else 0.0

    started = datetime.fromisoformat(round_row["started_at"])
    hidden_position = {number: index for index, number in enumerate(hidden, start=1)}
    for number in (1, 2, 3):
        raw_original = round_row[f"hint_{number}_scheduled_at"]
        normal_due = (
            datetime.fromisoformat(raw_original)
            if raw_original
            else started + timedelta(days=number * 2)
        )
        if number not in hidden_position:
            schedules[number] = normal_due
            continue

        accelerated_due = accelerated_at + timedelta(
            seconds=slot_seconds * hidden_position[number]
        )
        schedules[number] = min(normal_due, accelerated_due)

    return effective_end, schedules


def is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False

    # Administration du jeu : rôle Discord dédié.
    if config.game_admin_role_id is not None:
        role_ids = {role.id for role in interaction.user.roles}
        if config.game_admin_role_id in role_ids:
            return True

    # Filet de sécurité : les administrateurs du serveur et les membres
    # ayant la permission Gérer le serveur conservent aussi l'accès.
    return bool(
        interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_guild
    )


async def random_registered_participant(guild: discord.Guild, excluded: set[int]) -> int | None:
    """Tire au sort uniquement parmi les utilisateurs inscrits avec /participer."""
    participant_ids = await db.active_participant_ids(guild.id)
    eligible: list[int] = []
    for user_id in participant_ids:
        if user_id in excluded:
            continue
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        if not member.bot:
            eligible.append(user_id)

    if not eligible:
        return None

    import random
    return random.choice(eligible)


async def build_help_text(interaction: discord.Interaction) -> str:
    settings: list[str] = []
    if interaction.guild_id is not None:
        state = await db.get_state(interaction.guild_id)
        period = await db.get_current_period(interaction.guild_id)
        progress, period_limit = await db.period_progress(period["id"])
        active_round = await db.get_active_round(interaction.guild_id)

        if active_round is not None:
            attempt_limit = active_round["attempt_limit"]
            attempt_label = (
                "**illimités** pour la manche en cours"
                if attempt_limit is None
                else f"**{attempt_limit} par joueur** pour la manche en cours"
            )
        else:
            attempt_limit = state["default_attempt_limit"]
            attempt_label = (
                "**illimités**"
                if attempt_limit is None
                else f"**{attempt_limit} par joueur**"
            )

        if period_limit is None:
            period_label = f"**Période {period['number']}** — sans limite de manches"
        else:
            period_label = f"**Période {period['number']}** — **{progress}/{period_limit} manches**"

        settings = [
            "**Paramètres actuels**",
            f"🎯 Essais : {attempt_label}",
            f"🗓️ Classement : {period_label}",
            "⏱️ Durée maximale d’une manche : **7 jours**",
            "⚡ Accélération : **24 h maximum après la première bonne réponse validée**",
            "",
        ]

    text = settings + [
        "**Règles en bref**",
        "• **`/participer`** est requis pour répondre et être tiré au sort.",
        "• Manche : **7 jours max**, indices à **J+2/J+4/J+6** ; après la 1re bonne réponse validée, fin sous **24 h max**.",
        "• Essais : **illimités ou limités** selon la manche.",
        "• Verdict envoyé en privé après validation.",
        "• Podium : **6/5/4** avant tout indice, puis **5/4/3**, **4/3/2**, et **3/2/1** après le 3e ; **1 pt à partir de la 4e place**.",
        "• Si personne ne trouve : **+4 pts au meneur**.",
        "• Le 1er devient meneur ; s’il passe, un participant est tiré au sort.",
        "• Classement par **périodes** ; `/score` affiche la période en cours.",
        "",
        "**Commandes du meneur**",
        "`/lancer image:...` ou `/lancer url:...` — lancer une manche et saisir ses 3 indices",
        "`/passe` — passer la main avant de lancer la manche",
        "",
        "**Commandes joueurs**",
        "`/participer` — s’inscrire au jeu",
        "`/quitter` — se désinscrire du jeu",
        "`/participants` — afficher la liste des participants inscrits",
        "`/reponse` — proposer une réponse secrète",
        "`/score` — classement de la période actuelle ou d’une période choisie",
        "`/score-global` — classement toutes périodes confondues",
        "`/periodes` — afficher les périodes disponibles",
        "`/meneur` — afficher le meneur actuel",
        "`/historique` — afficher les dernières manches",
    ]
    if is_admin(interaction):
        text += [
            "",
            "**Administration**",
            "`/designer @joueur` — désigner le meneur",
            "`/corriger @joueur points:` — corriger le score de la période actuelle",
            "`/periode statut` / `config` — configurer la durée des périodes",
            "`/essais statut` / `config` — configurer le nombre d’essais par joueur",
            "`/cloturer` — clôturer immédiatement la manche",
            "`/tableau` — créer ou actualiser le scoreboard permanent",
            "`/reinitialiser` — remettre entièrement le jeu à zéro",
        ]
    text += ["", f"*Guess the Pix • v{BOT_VERSION.split('-', 1)[0]}*"]
    return "\n".join(text)


async def build_leaderboard_embed(
    guild_id: int,
    period_number: int | None = None,
    global_scores: bool = False,
) -> discord.Embed:
    period = None
    if not global_scores:
        if period_number is None:
            period = await db.get_current_period(guild_id)
        else:
            period = await db.get_period_by_number(guild_id, period_number)
            if period is None:
                return discord.Embed(
                    title=f"🏆 Classement — Période {period_number}",
                    description="Cette période n’existe pas.",
                )
        rows = await db.leaderboard(guild_id, period_id=period["id"])
        title = f"🏆 Classement — Période {period['number']}"
    else:
        rows = await db.leaderboard(guild_id)
        title = "🏆 Classement global"

    if not rows:
        embed = discord.Embed(title=title, description="Le classement est encore vide.")
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"**{i + 1}.**"
            lines.append(
                f"{prefix} <@{row['user_id']}> — **{row['score']} pt{'s' if row['score'] != 1 else ''}**"
            )
        embed = discord.Embed(title=title, description="\n".join(lines))

    if period is not None:
        progress, limit = await db.period_progress(period["id"])
        if limit:
            embed.set_footer(text=f"Période {period['number']} • {progress}/{limit} manches")
        elif period["status"] == "active":
            embed.set_footer(text=f"Période {period['number']} • durée illimitée")
    return embed


class RoundActionsView(discord.ui.View):
    """Boutons persistants affichés sous chaque message de manche."""

    def __init__(self, bot: "ScoreBot"):
        super().__init__(timeout=None)
        self.bot = bot

    async def _check_context(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Ces boutons sont disponibles uniquement sur le serveur.",
                ephemeral=True,
            )
            return False
        if not game_channel_ok(interaction):
            await interaction.response.send_message(
                "Cette action doit être utilisée dans le canal du jeu.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Participer",
        emoji="🎮",
        style=discord.ButtonStyle.success,
        custom_id="round_action:join",
    )
    async def participate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_context(interaction):
            return
        if await db.is_participant_active(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message("Tu participes déjà.", ephemeral=True)
            return

        await db.set_participant(interaction.guild_id, interaction.user.id, True)
        await interaction.response.send_message(
            "✅ Tu participes maintenant au jeu. Tu peux utiliser `/reponse` pendant les manches et tu es éligible aux tirages au sort.",
            ephemeral=True,
        )
        await self.bot.update_scoreboard(interaction.guild_id)

    @discord.ui.button(
        label="Répondre",
        emoji="💡",
        style=discord.ButtonStyle.primary,
        custom_id="round_action:answer",
    )
    async def answer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_context(interaction):
            return
        if not await db.is_participant_active(interaction.guild_id, interaction.user.id):
            participate = self.bot.command_mention("participer")
            await interaction.response.send_message(
                f"Tu dois d’abord t’inscrire avec {participate}.",
                ephemeral=True,
            )
            return

        round_row = await db.get_open_round(interaction.guild_id)
        if not round_row:
            await interaction.response.send_message(
                "Aucune manche n’est actuellement ouverte.",
                ephemeral=True,
            )
            return
        if datetime.fromisoformat(round_row["ends_at"]) <= datetime.now(timezone.utc):
            await interaction.response.send_message("Le délai de réponse est terminé.", ephemeral=True)
            return
        if interaction.user.id == round_row["master_id"]:
            await interaction.response.send_message(
                "Le meneur ne peut pas répondre à sa propre manche.",
                ephemeral=True,
            )
            return
        if await db.user_has_correct_attempt(round_row["id"], interaction.user.id):
            await interaction.response.send_message("Tu as déjà trouvé le jeu pour cette manche.", ephemeral=True)
            return
        if round_row["attempt_limit"] is not None:
            used = await db.user_attempt_count(round_row["id"], interaction.user.id)
            if used >= int(round_row["attempt_limit"]):
                await interaction.response.send_message(
                    f"Tu as déjà utilisé tes **{round_row['attempt_limit']} essais** pour cette manche.",
                    ephemeral=True,
                )
                return

        answer_command = self.bot.command_mention("reponse")
        await interaction.response.send_message(
            f"💡 Utilise {answer_command} pour proposer secrètement le nom du jeu.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Classement",
        emoji="🏆",
        style=discord.ButtonStyle.secondary,
        custom_id="round_action:score",
    )
    async def leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_context(interaction):
            return
        embed = await build_leaderboard_embed(interaction.guild_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Aide",
        emoji="❓",
        style=discord.ButtonStyle.secondary,
        custom_id="round_action:help",
    )
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_context(interaction):
            return
        await interaction.response.send_message(await build_help_text(interaction), ephemeral=True)


class ValidationView(discord.ui.View):
    def __init__(self, attempt_id: int):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Valider",
                style=discord.ButtonStyle.success,
                custom_id=f"answer:correct:{attempt_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Invalider",
                style=discord.ButtonStyle.danger,
                custom_id=f"answer:incorrect:{attempt_id}",
            )
        )



class ResetConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, bot: "ScoreBot"):
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Seule la personne ayant demandé la réinitialisation peut confirmer.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Tout effacer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild_id is None or not is_admin(interaction):
            await interaction.response.send_message(
                "Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.",
                ephemeral=True,
            )
            return

        # Le reset peut effectuer plusieurs opérations SQLite et une mise à jour du
        # scoreboard. On acquitte donc immédiatement le clic pour ne pas laisser
        # expirer l'interaction Discord.
        await interaction.response.defer()
        await db.reset_guild(interaction.guild_id)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(
            content=(
                "✅ **Jeu entièrement réinitialisé.**\n"
                "Scores, historique, manches, tentatives et meneur ont été effacés. "
                "La prochaine manche recommencera à **#1**."
            ),
            view=self,
        )
        await self.bot.update_scoreboard(interaction.guild_id)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Réinitialisation annulée.",
            view=self,
        )
        self.stop()


class StartRoundModal(discord.ui.Modal, title="Lancer la manche"):
    solution = discord.ui.TextInput(
        label="Réponse attendue (cachée aux joueurs)",
        placeholder="Nom exact du jeu",
        max_length=200,
    )
    hint_1 = discord.ui.TextInput(
        label="Indice 1 — prévu à J+2",
        placeholder="Premier indice",
        max_length=300,
    )
    hint_2 = discord.ui.TextInput(
        label="Indice 2 — prévu à J+4",
        placeholder="Deuxième indice",
        max_length=300,
    )
    hint_3 = discord.ui.TextInput(
        label="Indice 3 — prévu à J+6",
        placeholder="Troisième indice",
        max_length=300,
    )

    def __init__(
        self,
        bot: "ScoreBot",
        capture: discord.Attachment | None = None,
        image_url: str | None = None,
    ):
        super().__init__()
        self.bot = bot
        self.capture = capture
        self.image_url = image_url

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Cette commande doit être utilisée sur le serveur.", ephemeral=True)
            return

        active_round = await db.get_active_round(interaction.guild_id)
        if active_round:
            await interaction.response.send_message("Une manche est déjà en cours.", ephemeral=True)
            return

        state = await db.get_state(interaction.guild_id)
        if not state["current_master_id"]:
            await interaction.response.send_message("Aucun meneur n’est désigné. Un administrateur doit utiliser `/designer`.", ephemeral=True)
            return
        if state["current_master_id"] != interaction.user.id:
            await interaction.response.send_message("Seul le meneur désigné peut lancer la manche.", ephemeral=True)
            return

        # La lecture d'une pièce jointe et surtout le téléchargement d'une URL
        # peuvent dépasser la fenêtre de réponse de Discord. Le modal est donc
        # acquitté avant toute opération réseau potentiellement lente.
        await interaction.response.defer(thinking=True)
        try:
            image_data, image_filename = await self.bot.prepare_round_image_payload(self.capture, self.image_url)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        ends = now + timedelta(days=config.round_duration_days)
        hint_1_at = now + timedelta(days=2)
        hint_2_at = now + timedelta(days=4)
        hint_3_at = now + timedelta(days=6)
        period = await db.get_current_period(interaction.guild_id)
        attempt_limit = state["default_attempt_limit"]
        round_id = await db.create_round(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            master_id=interaction.user.id,
            period_id=period["id"],
            attempt_limit=attempt_limit,
            solution=str(self.solution).strip(),
            image_url=None,
            hint_1=str(self.hint_1).strip(),
            hint_2=str(self.hint_2).strip(),
            hint_3=str(self.hint_3).strip(),
            started_at=now.isoformat(),
            ends_at=ends.isoformat(),
            hint_1_scheduled_at=hint_1_at.isoformat(),
            hint_2_scheduled_at=hint_2_at.isoformat(),
            hint_3_scheduled_at=hint_3_at.isoformat(),
        )

        await self.bot.save_round_image_cache(round_id, image_data, image_filename)
        upload_file = self.bot.make_discord_file(image_data, image_filename)

        round_content = (
            f"## 🎮 Manche #{round_id}\n"
            f"Proposée par {interaction.user.mention}\n"
            f"**Pour participer :** utilisez les boutons ci-dessous, ou **`/participer`** puis **`/reponse`**.\n"
            f"💡 Trois indices sont prévus à **J+2, J+4 et J+6**.\n"
            f"⚡ Dès la première bonne réponse validée, il restera **24 h maximum** et les indices encore cachés seront rapprochés.\n"
            f"🎯 Essais : **{'illimités' if attempt_limit is None else str(attempt_limit) + ' par joueur'}**.\n\n"
            f"Fin maximale : <t:{int(ends.timestamp())}:F> — <t:{int(ends.timestamp())}:R>"
        )
        message = await interaction.followup.send(
            content=round_content,
            file=upload_file,
            view=RoundActionsView(self.bot),
            wait=True,
        )

        if message is not None:
            image_url = message.attachments[0].url if message.attachments else None
            await db.update_round_message_reference(round_id, message.id, image_url)

        await self.bot.update_scoreboard(interaction.guild_id)


class ScoreBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.command_mentions: dict[str, str] = {}
        self.round_images_dir = config.database_path.parent / "round_images"
        self.round_images_dir.mkdir(parents=True, exist_ok=True)

    def command_mention(self, name: str) -> str:
        return self.command_mentions.get(name, f"`/{name}`")

    async def setup_hook(self) -> None:
        await db.init()
        # Vue persistante : les boutons des anciennes manches restent actifs après redémarrage.
        self.add_view(RoundActionsView(self))
        logger.warning("Scoreboard bot version %s", BOT_VERSION)

        if config.guild_id:
            guild = discord.Object(id=config.guild_id)

            # Les commandes de ce bot doivent vivre uniquement sur ce serveur.
            # On copie d'abord les définitions courantes vers le serveur puis on
            # les synchronise. Cela remplace aussi les anciennes commandes de guilde.
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            self.command_mentions = {
                command.name: f"</{command.name}:{command.id}>"
                for command in synced
                if command.id
            }
            logger.warning(
                "Commandes synchronisees sur le serveur %s : %s",
                config.guild_id,
                ", ".join(sorted(command.name for command in synced)),
            )

            # Une ancienne version du bot a pu enregistrer les commandes globalement.
            # On supprime explicitement ces anciennes commandes côté Discord afin
            # d'éviter qu'elles restent visibles pendant leur délai de propagation.
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.warning("Anciennes commandes globales supprimees.")
        else:
            synced = await self.tree.sync()
            self.command_mentions = {
                command.name: f"</{command.name}:{command.id}>"
                for command in synced
                if command.id
            }
            logger.warning(
                "Commandes globales synchronisees : %s",
                ", ".join(sorted(command.name for command in synced)),
            )

        self.close_due_rounds.start()

    def make_discord_file(self, data: bytes, filename: str) -> discord.File:
        return discord.File(io.BytesIO(data), filename=filename)

    def round_image_cache_path(self, round_id: int, filename: str) -> Path:
        safe_name = filename.strip().replace(chr(92), "_").replace("/", "_") or "capture.png"
        suffix = Path(safe_name).suffix or ".png"
        return self.round_images_dir / f"round_{round_id}{suffix}"

    async def save_round_image_cache(self, round_id: int, data: bytes, filename: str) -> Path:
        path = self.round_image_cache_path(round_id, filename)
        for existing in self.round_images_dir.glob(f"round_{round_id}.*"):
            if existing != path:
                try:
                    existing.unlink()
                except OSError:
                    pass
        path.write_bytes(data)
        logger.info("Round %s image cached locally at %s", round_id, path)
        return path

    async def load_round_image_cache(self, round_id: int) -> tuple[bytes, str] | None:
        for path in sorted(self.round_images_dir.glob(f"round_{round_id}.*")):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if data:
                logger.info("Round %s image loaded from local cache", round_id)
                return data, path.name
        return None

    async def prepare_round_image_payload(
        self,
        capture: discord.Attachment | None,
        image_url: str | None,
    ) -> tuple[bytes, str]:
        if capture is None and not image_url:
            raise ValueError("Vous devez fournir soit une image, soit une URL d’image.")
        if capture is not None and image_url:
            raise ValueError("Choisissez soit une image, soit une URL d’image, pas les deux.")

        data: bytes
        filename: str
        content_type: str | None = None

        if capture is not None:
            content_type = capture.content_type
            if content_type and not content_type.startswith("image/"):
                raise ValueError("La capture doit être une image.")
            try:
                data = await capture.read()
            except discord.HTTPException as exc:
                raise ValueError("Impossible de lire l’image envoyée.") from exc
            filename = capture.filename or "capture"
        else:
            raw_url = (image_url or "").strip()
            parsed = urlparse(raw_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("L’URL doit être une adresse http(s) publique pointant vers une image.")
            timeout = aiohttp.ClientTimeout(total=20)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(raw_url, allow_redirects=True) as response:
                        if response.status != 200:
                            raise ValueError(f"Impossible de récupérer l’image (HTTP {response.status}).")
                        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
                        if not content_type.startswith("image/"):
                            raise ValueError("L’URL fournie ne pointe pas vers une image exploitable.")
                        data = await response.read()
            except asyncio.TimeoutError as exc:
                raise ValueError("Le téléchargement de l’image a expiré.") from exc
            except aiohttp.ClientError as exc:
                raise ValueError("Impossible de télécharger l’image depuis cette URL.") from exc

            filename = unquote(parsed.path.rsplit("/", 1)[-1]) or "capture"

        if not data:
            raise ValueError("L’image fournie est vide.")
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("L’image dépasse 8 Mo, ce qui est trop lourd pour cette commande.")

        filename = filename.strip().replace(chr(92), "_").replace("/", "_") or "capture"
        if "." not in filename:
            ext = mimetypes.guess_extension(content_type or "") or ".png"
            filename = f"{filename}{ext}"

        return data, filename

    async def prepare_round_image(
        self,
        capture: discord.Attachment | None,
        image_url: str | None,
    ) -> discord.File:
        data, filename = await self.prepare_round_image_payload(capture, image_url)
        return self.make_discord_file(data, filename)

    async def prepare_round_repost_image(self, round_row) -> discord.File | None:
        """Build a fresh Discord upload for a round screenshot."""
        round_id = int(round_row["id"])

        cached = await self.load_round_image_cache(round_id)
        if cached is not None:
            data, filename = cached
            return self.make_discord_file(data, filename)

        channel = self.get_channel(int(round_row["channel_id"]))
        if channel is None:
            try:
                channel = await self.fetch_channel(int(round_row["channel_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None

        attachment = None
        source_message = None

        if channel is not None and hasattr(channel, "fetch_message"):
            message_id = round_row["round_message_id"]
            if message_id:
                try:
                    source_message = await channel.fetch_message(int(message_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    source_message = None

            if source_message is None and hasattr(channel, "history"):
                started_at = datetime.fromisoformat(round_row["started_at"])
                after = started_at - timedelta(minutes=2)
                before = started_at + timedelta(minutes=15)
                expected_title = f"🎮 Manche #{round_row['id']}"
                try:
                    async for message in channel.history(
                        limit=100, after=after, before=before, oldest_first=True
                    ):
                        if self.user is not None and message.author.id != self.user.id:
                            continue
                        if not message.attachments:
                            continue
                        has_legacy_embed = any(embed.title == expected_title for embed in message.embeds)
                        has_plain_launch = (message.content or "").startswith(f"## {expected_title}")
                        if not has_legacy_embed and not has_plain_launch:
                            continue
                        source_message = message
                        await db.update_round_message_reference(
                            round_id,
                            int(message.id),
                            message.attachments[0].url,
                        )
                        break
                except (discord.Forbidden, discord.HTTPException):
                    source_message = None

        if source_message is not None and source_message.attachments:
            attachment = source_message.attachments[0]
            await db.update_round_message_reference(
                round_id, int(source_message.id), attachment.url
            )
            try:
                data = await attachment.read()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                try:
                    data = await attachment.read(use_cached=True)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    data = b""

            if data:
                filename = (attachment.filename or "capture").strip()
                filename = filename.replace(chr(92), "_").replace("/", "_") or "capture"
                if "." not in filename:
                    content_type = attachment.content_type or ""
                    ext = mimetypes.guess_extension(content_type) or ".png"
                    filename = f"{filename}{ext}"
                await self.save_round_image_cache(round_id, data, filename)
                return self.make_discord_file(data, filename)

        fallback_url = round_row["image_url"]
        if fallback_url:
            timeout = aiohttp.ClientTimeout(total=20)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(str(fallback_url), allow_redirects=True) as response:
                        if response.status == 200:
                            data = await response.read()
                            if data:
                                content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
                                ext = mimetypes.guess_extension(content_type) or ".png"
                                filename = f"round_{round_id}{ext}"
                                await self.save_round_image_cache(round_id, data, filename)
                                return self.make_discord_file(data, filename)
            except (asyncio.TimeoutError, aiohttp.ClientError):
                pass

        logger.warning(
            "Impossible de recuperer la capture de la manche %s pour reupload",
            round_row["id"],
        )
        return None

    async def attach_round_image(self, embed: discord.Embed, round_row) -> discord.File | None:
        """Attach a fresh copy of the round screenshot to a new Discord message."""
        image_file = await self.prepare_round_repost_image(round_row)
        if image_file is not None:
            embed.set_image(url=f"attachment://{image_file.filename}")
        return image_file

    async def build_scoreboard_embed(self, guild_id: int) -> discord.Embed:
        state = await db.get_state(guild_id)
        period = await db.get_current_period(guild_id)
        rows = await db.leaderboard(guild_id, limit=20, period_id=period["id"])

        if rows:
            medals = ["🥇", "🥈", "🥉"]
            score_lines = []
            for i, row in enumerate(rows):
                prefix = medals[i] if i < 3 else f"**{i + 1}.**"
                score_lines.append(
                    f"{prefix} <@{row['user_id']}> — **{row['score']} pt{'s' if row['score'] != 1 else ''}**"
                )
        else:
            score_lines = ["Aucun point attribué pour le moment."]

        embed = discord.Embed(
            title=f"🏆 Scoreboard — Période {period['number']}",
            description="\n".join(score_lines),
        )

        active_round = await db.get_active_round(guild_id)
        if active_round:
            if active_round["status"] == "open":
                participant_count = await db.round_participant_count(active_round["id"])
                hint_status_text = ""
                if round_has_hints(active_round):
                    revealed_count = sum(
                        1 for index in (1, 2, 3) if active_round[f"hint_{index}_revealed_at"]
                    )
                    next_hint_text = ""
                    unrevealed = [
                        index for index in (1, 2, 3)
                        if not active_round[f"hint_{index}_revealed_at"]
                    ]
                    if unrevealed:
                        next_hint_number = unrevealed[0]
                        raw_next_hint_at = active_round[f"hint_{next_hint_number}_scheduled_at"]
                        if raw_next_hint_at:
                            next_hint_at = datetime.fromisoformat(raw_next_hint_at)
                            next_hint_text = f" — prochain <t:{int(next_hint_at.timestamp())}:R>"
                    hint_status_text = f"\nIndices révélés : **{revealed_count}/3**{next_hint_text}"
                accelerated_text = (
                    f"\n⚡ Mode accéléré actif depuis {discord_ts(active_round['accelerated_at'], 'R')}"
                    if active_round["accelerated_at"] else ""
                )
                round_text = (
                    f"**Manche #{active_round['id']} en cours**\n"
                    f"Meneur : <@{active_round['master_id']}>\n"
                    f"Fin : {discord_ts(active_round['ends_at'], 'F')} ({discord_ts(active_round['ends_at'], 'R')})"
                    f"{accelerated_text}"
                    f"{hint_status_text}\n"
                    f"Participants ayant répondu : **{participant_count}**"
                )
            else:
                round_text = (
                    f"**Manche #{active_round['id']} terminée**\n"
                    f"Meneur : <@{active_round['master_id']}>\n"
                    "Validation des dernières réponses en cours."
                )
        elif state["current_master_id"]:
            round_text = f"Aucune manche en cours.\n🎮 Prochain meneur : <@{state['current_master_id']}>"
        else:
            round_text = "Aucune manche en cours et aucun meneur désigné."

        registered_count = await db.active_participant_count(guild_id)
        embed.add_field(name="État du jeu", value=round_text, inline=False)
        embed.add_field(name="Participants inscrits", value=f"**{registered_count}**", inline=True)
        progress, limit = await db.period_progress(period["id"])
        period_status = f"{progress}/{limit} manches" if limit else "durée illimitée"
        embed.add_field(name="Période", value=f"**{period['number']}** — {period_status}", inline=True)
        embed.set_footer(text=f"Mise à jour automatique • bot {BOT_VERSION}")
        return embed


    async def update_scoreboard(self, guild_id: int, create_if_missing: bool = False) -> discord.Message | None:
        state = await db.get_state(guild_id)
        channel_id = state["scoreboard_channel_id"] or config.game_channel_id
        message_id = state["scoreboard_message_id"]

        if not channel_id:
            return None

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        if not isinstance(channel, discord.TextChannel):
            return None

        embed = await self.build_scoreboard_embed(guild_id)

        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return message
            except discord.NotFound:
                await db.clear_scoreboard_message(guild_id)
            except (discord.Forbidden, discord.HTTPException):
                return None

        if not create_if_missing:
            return None

        try:
            message = await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return None
        await db.set_scoreboard_message(guild_id, channel.id, message.id)
        return message

    async def notify_new_leader(self, guild_id: int, user_id: int) -> bool:
        user = self.get_user(user_id)
        if user is None:
            try:
                user = await self.fetch_user(user_id)
            except discord.HTTPException:
                return False

        channel_label = "le salon du jeu"
        if config.game_channel_id:
            channel = self.get_channel(config.game_channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(config.game_channel_id)
                except discord.HTTPException:
                    channel = None
            if isinstance(channel, discord.TextChannel):
                channel_label = f"#{channel.name}"

        try:
            await user.send(
                "🎮 **Tu es le prochain meneur !**\n\n"
                f"Dans **{channel_label}**, tu peux utiliser :\n"
                "**`/lancer`** — lancer la prochaine manche avec une image ou une URL, le nom du jeu et les 3 indices.\n"
                "**`/passe`** — passer la main si tu ne souhaites pas proposer de manche.\n\n"
                "Une manche dure au maximum 7 jours et passe en mode accéléré pendant 24 h après la première bonne réponse validée."
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def send_player_message(self, user_id: int, message: str) -> bool:
        user = self.get_user(user_id)
        if user is None:
            try:
                user = await self.fetch_user(user_id)
            except discord.HTTPException:
                return False
        try:
            await user.send(message)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def finalize_confirmable_results(self, round_id: int) -> set[int]:
        """Attribue et notifie uniquement les positions devenues certaines."""
        round_row = await db.get_round(round_id)
        if not round_row:
            return set()

        finalized_users: set[int] = set()
        candidates = list(await db.first_correct_attempts(round_id))
        hints_enabled = round_has_hints(round_row)
        for rank, attempt in enumerate(candidates, start=1):
            if attempt["result_notified_at"]:
                continue
            # Une réponse encore en attente, envoyée plus tôt, pourrait modifier le rang.
            if await db.pending_before(round_id, attempt["submitted_at"]):
                continue

            stage = hint_stage_for_submission(round_row, attempt["submitted_at"]) if hints_enabled else 3
            points = points_for_rank(rank, stage)

            changed = await db.finalize_correct_result(
                attempt_id=attempt["id"],
                guild_id=round_row["guild_id"],
                user_id=attempt["user_id"],
                round_id=round_id,
                period_id=round_row["period_id"],
                rank=rank,
                points=points,
            )
            if not changed:
                continue

            finalized_users.add(int(attempt["user_id"]))
            position = french_rank(rank)
            await self.send_player_message(
                attempt["user_id"],
                "✅ **Bonne réponse !**\n"
                f"Bravo, tu as trouvé et tu es **{position}**.\n"
                f"Tu marques **{points} point{'s' if points != 1 else ''}**.",
            )

        if finalized_users:
            await self.update_scoreboard(round_row["guild_id"])
        return finalized_users

    async def notify_leader(
        self,
        round_row,
        attempt_id: int,
        player: discord.abc.User,
        answer: str,
    ) -> None:
        leader = self.get_user(round_row["master_id"])
        if leader is None:
            try:
                leader = await self.fetch_user(round_row["master_id"])
            except discord.HTTPException:
                leader = None

        delivered = False
        if leader:
            embed = discord.Embed(title=f"Réponse à valider — Manche #{round_row['id']}")
            embed.add_field(name="Joueur", value=f"{player} (`{player.id}`)", inline=False)
            embed.add_field(name="Réponse", value=answer, inline=False)
            embed.add_field(name="Tentative", value=f"#{attempt_id}", inline=False)
            try:
                await leader.send(embed=embed, view=ValidationView(attempt_id))
                delivered = True
            except discord.Forbidden:
                pass

        if not delivered:
            channel = self.get_channel(round_row["channel_id"])
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send(
                        f"<@{round_row['master_id']}> je n’ai pas pu t’envoyer en privé une réponse à valider. "
                        "Vérifie que tes messages privés sont autorisés pour ce serveur."
                    )
                except discord.HTTPException:
                    pass

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        data = interaction.data or {}
        custom_id = data.get("custom_id") if isinstance(data, dict) else None
        if not custom_id or not custom_id.startswith("answer:"):
            return

        parts = custom_id.split(":")
        if len(parts) != 3:
            return
        _, status, raw_attempt_id = parts
        if status not in {"correct", "incorrect"} or not raw_attempt_id.isdigit():
            return

        attempt = await db.get_attempt(int(raw_attempt_id))
        if not attempt:
            await interaction.response.send_message("Tentative introuvable.", ephemeral=True)
            return
        if attempt["round_status"] not in {"open", "review"}:
            await interaction.response.send_message("Cette manche est déjà terminée.", ephemeral=True)
            return
        if interaction.user.id != attempt["master_id"]:
            await interaction.response.send_message("Seul le meneur peut valider cette réponse.", ephemeral=True)
            return

        changed = await db.review_attempt(int(raw_attempt_id), interaction.user.id, status)
        if not changed:
            await interaction.response.send_message("Cette réponse a déjà été examinée.", ephemeral=True)
            return

        verdict = "validée" if status == "correct" else "invalidée"
        await interaction.response.send_message(f"Réponse {verdict}.", ephemeral=True)

        # On fige le message privé du meneur afin d’éviter une seconde validation
        # accidentelle et de garder un historique clair.
        if interaction.message is not None:
            try:
                embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed(
                    title=f"Réponse — Manche #{attempt['round_id']}"
                )
                embed.add_field(
                    name="Statut",
                    value="✅ Validée" if status == "correct" else "❌ Invalidée",
                    inline=False,
                )
                await interaction.message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        if status == "correct":
            reviewed_attempt = await db.get_attempt(int(raw_attempt_id))
            if reviewed_attempt and reviewed_attempt["reviewed_at"]:
                await self.trigger_acceleration(
                    reviewed_attempt["round_id"],
                    datetime.fromisoformat(reviewed_attempt["reviewed_at"]),
                )

            finalized = await self.finalize_confirmable_results(attempt["round_id"])
            if int(attempt["user_id"]) not in finalized:
                await self.send_player_message(
                    attempt["user_id"],
                    "✅ **Bonne réponse !**\n"
                    "Bravo, tu as trouvé.\n"
                    "Ta position et tes points seront confirmés dès que les réponses précédentes auront été arbitrées.",
                )
        else:
            used = await db.user_attempt_count(attempt["round_id"], attempt["user_id"])
            limit = attempt["attempt_limit"]
            if limit is None:
                if attempt["round_status"] == "review":
                    message = (
                        "❌ **Mauvaise réponse.**\n"
                        "La manche est désormais close aux nouvelles réponses."
                    )
                else:
                    message = (
                        "❌ **Mauvaise réponse.**\n"
                        "Tu peux réessayer avec `/reponse`."
                    )
            else:
                remaining_attempts = max(0, int(limit) - used)
                if remaining_attempts > 0:
                    if attempt["round_status"] == "review":
                        message = (
                            "❌ **Mauvaise réponse.**\n"
                            f"Il te restait **{remaining_attempts} essai{'s' if remaining_attempts != 1 else ''}**, "
                            "mais la manche est désormais close aux nouvelles réponses."
                        )
                    else:
                        message = (
                            "❌ **Mauvaise réponse.**\n"
                            f"Il te reste **{remaining_attempts} essai{'s' if remaining_attempts != 1 else ''}** pour cette manche."
                        )
                else:
                    message = (
                        "❌ **Mauvaise réponse.**\n"
                        "Tu as utilisé tous tes essais pour cette manche."
                    )
            await self.send_player_message(attempt["user_id"], message)
            # Une invalidation peut lever l’incertitude sur le rang d’une bonne réponse plus tardive.
            await self.finalize_confirmable_results(attempt["round_id"])

        refreshed = await db.get_attempt(int(raw_attempt_id))
        if refreshed and refreshed["round_status"] == "review":
            remaining = await db.pending_attempts(refreshed["round_id"])
            if not remaining:
                await self.finish_round(refreshed["round_id"])

    async def trigger_acceleration(self, round_id: int, accelerated_at: datetime) -> bool:
        round_row = await db.get_round(round_id)
        if not round_row or round_row["status"] != "open" or round_row["accelerated_at"]:
            return False

        effective_end, schedules = compute_accelerated_timing(round_row, accelerated_at)
        if effective_end <= accelerated_at:
            return False

        changed = await db.accelerate_round(
            round_id=round_id,
            accelerated_at=accelerated_at.isoformat(),
            ends_at=effective_end.isoformat(),
            hint_1_scheduled_at=schedules[1].isoformat(),
            hint_2_scheduled_at=schedules[2].isoformat(),
            hint_3_scheduled_at=schedules[3].isoformat(),
        )
        if not changed:
            return False

        refreshed = await db.get_round(round_id)
        channel = self.get_channel(refreshed["channel_id"])
        if channel is None:
            try:
                channel = await self.fetch_channel(refreshed["channel_id"])
            except discord.HTTPException:
                channel = None

        if isinstance(channel, discord.abc.Messageable):
            acceleration_content = (
                f"## ⚡ Manche #{round_id} - Le jeu s’accélère !\n"
                "Une première bonne réponse a été validée. Son auteur reste secret jusqu’à la fin.\n\n"
                f"Les autres participants ont désormais jusqu’à <t:{int(effective_end.timestamp())}:F> "
                f"(<t:{int(effective_end.timestamp())}:R>) pour répondre.\n"
                "Les indices encore cachés sont rapprochés en conséquence."
            )
            image_file = await self.prepare_round_repost_image(refreshed)
            send_kwargs = {"content": acceleration_content, "view": RoundActionsView(self)}
            if image_file is not None:
                send_kwargs["file"] = image_file
            try:
                await channel.send(**send_kwargs)
            except discord.HTTPException:
                pass

        await self.update_scoreboard(refreshed["guild_id"])
        # Publie immédiatement un indice dont l’horaire normal était déjà dépassé.
        await self.publish_due_hints()
        return True

    async def publish_due_hints(self) -> None:
        now = datetime.now(timezone.utc)
        for round_row in await db.open_rounds():
            if not round_has_hints(round_row):
                continue
            for hint_number in (1, 2, 3):
                if round_row[f"hint_{hint_number}_revealed_at"]:
                    continue
                raw_due_at = round_row[f"hint_{hint_number}_scheduled_at"]
                if not raw_due_at:
                    started = datetime.fromisoformat(round_row["started_at"])
                    due_at = started + timedelta(days=hint_number * 2)
                else:
                    due_at = datetime.fromisoformat(raw_due_at)
                if now < due_at:
                    continue

                channel = self.get_channel(round_row["channel_id"])
                if channel is None:
                    try:
                        channel = await self.fetch_channel(round_row["channel_id"])
                    except discord.HTTPException:
                        channel = None
                if not isinstance(channel, discord.abc.Messageable):
                    continue

                remaining_points = {1: "5 / 4 / 3", 2: "4 / 3 / 2", 3: "3 / 2 / 1"}[hint_number]
                hint_content = (
                    f"💡 Manche #{round_row['id']} - Indice {hint_number}/3\n\n"
                    f"**{round_row[f'hint_{hint_number}']}**\n\n"
                    f"*Barème du podium à partir de maintenant : {remaining_points} points • 1 pt à partir de la 4e place*"
                )
                image_file = await self.prepare_round_repost_image(round_row)
                send_kwargs = {"content": hint_content, "view": RoundActionsView(self)}
                if image_file is not None:
                    send_kwargs["file"] = image_file
                try:
                    hint_message = await channel.send(**send_kwargs)
                except discord.HTTPException:
                    continue

                revealed_at = hint_message.created_at.isoformat()
                if await db.mark_hint_revealed(round_row["id"], hint_number, revealed_at):
                    round_row = await db.get_round(round_row["id"])
                    await self.update_scoreboard(round_row["guild_id"])

    @tasks.loop(seconds=60)
    async def close_due_rounds(self) -> None:
        await self.publish_due_hints()
        due = await db.due_rounds(datetime.now(timezone.utc).isoformat())
        for row in due:
            await self.lock_round_and_maybe_finish(row["id"])

    @close_due_rounds.before_loop
    async def before_close_due_rounds(self) -> None:
        await self.wait_until_ready()

    async def lock_round_and_maybe_finish(self, round_id: int) -> bool:
        round_row = await db.get_round(round_id)
        if not round_row or round_row["status"] == "closed":
            return False

        if round_row["status"] == "open":
            await db.lock_round_for_review(round_id)
            round_row = await db.get_round(round_id)

        pending = await db.pending_attempts(round_id)
        if pending:
            master = self.get_user(round_row["master_id"])
            if master is None:
                try:
                    master = await self.fetch_user(round_row["master_id"])
                except discord.HTTPException:
                    master = None
            delivered = False
            if master:
                try:
                    await master.send(
                        f"⏰ La manche #{round_id} est terminée : les nouvelles réponses sont fermées. "
                        f"Il reste **{len(pending)} réponse(s)** à valider dans tes messages privés. "
                        "Le classement sera publié dès que toutes auront été examinées."
                    )
                    delivered = True
                except discord.Forbidden:
                    pass
            if not delivered:
                channel = self.get_channel(round_row["channel_id"])
                if isinstance(channel, discord.abc.Messageable):
                    await channel.send(
                        f"<@{round_row['master_id']}> les réponses de la manche #{round_id} sont closes ; "
                        f"{len(pending)} validation(s) restent en attente."
                    )
            return False

        await self.finish_round(round_id)
        return True

    async def finish_round(self, round_id: int) -> None:
        round_row = await db.get_round(round_id)
        if not round_row or round_row["status"] not in {"open", "review"}:
            return

        # À ce stade toutes les réponses sont arbitrées : tous les rangs deviennent certains.
        await self.finalize_confirmable_results(round_id)

        # On ferme ensuite pour éviter une double finalisation concurrente.
        if not await db.close_round(round_id):
            return
        round_row = await db.get_round(round_id)

        winners = list(await db.first_correct_attempts(round_id))
        hints_enabled = round_has_hints(round_row)
        winner_stages = [
            hint_stage_for_submission(round_row, row["submitted_at"]) if hints_enabled else 3
            for row in winners
        ]
        winner_points = [
            points_for_rank(rank, winner_stages[rank - 1])
            for rank in range(1, len(winners) + 1)
        ]

        # Recalcule le barème à la clôture à partir des horodatages réels. Cela
        # garantit notamment le +1 à partir de la 4e place, y compris si une
        # manche était déjà en cours lors de la mise à jour vers v0.13.0.
        for rank, (row, points) in enumerate(zip(winners, winner_points), start=1):
            reason = f"podium_{rank}" if rank <= 3 else "correct_after_podium"
            await db.add_score(
                round_row["guild_id"],
                row["user_id"],
                points,
                reason,
                round_id,
                period_id=round_row["period_id"],
            )

        podium = winners[:3]
        awarded_points = winner_points[:3]
        podium_stages = winner_stages[:3]

        next_master: int | None = None
        next_master_reason: str
        if podium:
            for winner in winners:
                if await db.is_participant_active(round_row["guild_id"], winner["user_id"]):
                    next_master = winner["user_id"]
                    break

            if next_master is None:
                guild = self.get_guild(round_row["guild_id"])
                next_master = (
                    await random_registered_participant(guild, excluded={round_row["master_id"]})
                    if guild is not None
                    else None
                )

            if next_master:
                await db.set_master(
                    round_row["guild_id"], next_master, previous_master_id=round_row["master_id"]
                )
                notified = await self.notify_new_leader(round_row["guild_id"], next_master)
                if next_master == podium[0]["user_id"]:
                    next_master_reason = f"🎮 <@{next_master}> devient le **prochain meneur**."
                else:
                    next_master_reason = f"🎮 <@{next_master}> devient le **prochain meneur** parmi les participants encore inscrits."
                if not notified:
                    next_master_reason += "\n⚠️ Impossible de lui envoyer les instructions en message privé."
            else:
                await db.clear_master(
                    round_row["guild_id"], previous_master_id=round_row["master_id"]
                )
                next_master_reason = (
                    "⚠️ Aucun participant inscrit n’est disponible pour devenir meneur. "
                    "Un Admin du jeu doit utiliser `/designer`."
                )
        else:
            await db.add_score(
                round_row["guild_id"],
                round_row["master_id"],
                4,
                "unfound_master_bonus",
                round_id,
                period_id=round_row["period_id"],
            )
            guild = self.get_guild(round_row["guild_id"])
            next_master = (
                await random_registered_participant(guild, excluded={round_row["master_id"]})
                if guild is not None
                else None
            )
            if next_master:
                await db.set_master(
                    round_row["guild_id"], next_master, previous_master_id=round_row["master_id"]
                )
                notified = await self.notify_new_leader(round_row["guild_id"], next_master)
                next_master_reason = (
                    f"🎲 Personne n’ayant trouvé, <@{next_master}> est **tiré au sort** "
                    "comme prochain meneur."
                )
                if not notified:
                    next_master_reason += "\n⚠️ Impossible de lui envoyer les instructions en message privé."
            else:
                await db.clear_master(
                    round_row["guild_id"], previous_master_id=round_row["master_id"]
                )
                next_master_reason = (
                    "⚠️ Aucun autre participant inscrit n’est éligible au tirage. "
                    "Un Admin du jeu doit utiliser `/designer`."
                )

        participant_count = await db.round_participant_count(round_id)
        attempt_count = await db.count_attempts(round_id)
        correct_count = len(winners)

        result_lines = [
            f"**🎮 Meneur de la manche**\n<@{round_row['master_id']}>"
        ]

        if podium:
            medals = ["🥇", "🥈", "🥉"]
            podium_lines = []
            for i, row in enumerate(podium):
                elapsed = format_elapsed(round_row["started_at"], row["submitted_at"])
                points = awarded_points[i]
                stage = podium_stages[i]
                timing_label = hint_stage_label(stage) if hints_enabled else "sans système d’indices"
                podium_lines.append(
                    f"{medals[i]} <@{row['user_id']}> — **+{points} pt{'s' if points > 1 else ''}** "
                    f"— trouvé en **{elapsed}**, {timing_label}"
                )
            result_lines.append("**🏆 Podium**\n" + "\n".join(podium_lines))
        else:
            result_lines.append(
                "**🔒 Introuvable**\n"
                f"Personne n’a trouvé : <@{round_row['master_id']}> gagne **+4 points**."
            )

        other_correct = max(0, correct_count - len(podium))
        bilan_lines = [
            f"👥 **{participant_count}** participant{'s' if participant_count != 1 else ''}",
            f"💬 **{attempt_count}** tentative{'s' if attempt_count != 1 else ''}",
            f"✅ **{correct_count}** joueur{'s' if correct_count != 1 else ''} "
            f"{'ont' if correct_count != 1 else 'a'} trouvé",
        ]
        if round_row["accelerated_at"]:
            accelerated_dt = datetime.fromisoformat(round_row["accelerated_at"])
            bilan_lines.append(f"⚡ Mode accéléré déclenché <t:{int(accelerated_dt.timestamp())}:R>")
        if other_correct:
            bilan_lines.append(
                f"👏 **{other_correct}** autre{'s' if other_correct != 1 else ''} bonne{'s' if other_correct != 1 else ''} "
                f"réponse{'s' if other_correct != 1 else ''} au-delà du podium — **+1 pt chacun**"
            )
        result_lines.append("**📊 Bilan de la manche**\n" + "\n".join(bilan_lines))
        result_lines.append("**🎮 Prochaine manche**\n" + next_master_reason)
        result_lines.append(
            "*Le podium dépend du rang et des indices révélés ; à partir de la 4e place, toute bonne réponse rapporte 1 point.*"
        )

        image_file = await self.prepare_round_repost_image(round_row)

        channel = self.get_channel(round_row["channel_id"])
        if channel is None:
            try:
                channel = await self.fetch_channel(round_row["channel_id"])
            except discord.HTTPException:
                channel = None
        if isinstance(channel, discord.abc.Messageable):
            result_content = (
                f"# 🎮 {round_row['solution']}\n"
                f"## Manche #{round_id} terminée !"
            )
            if image_file is not None:
                await channel.send(content=result_content, file=image_file)
            else:
                await channel.send(content=result_content)
            await channel.send(content="\n\n".join(result_lines))

        # Une période limitée se clôture une fois son nombre de manches atteint.
        period = await db.get_current_period(round_row["guild_id"])
        if period and int(period["id"]) == int(round_row["period_id"]):
            progress, limit = await db.period_progress(period["id"])
            if limit is not None and progress >= int(limit):
                period_rows = await db.leaderboard(
                    round_row["guild_id"], period_id=period["id"]
                )
                final_lines = []
                medals = ["🥇", "🥈", "🥉"]
                for i, row in enumerate(period_rows):
                    prefix = medals[i] if i < 3 else f"**{i + 1}.**"
                    final_lines.append(
                        f"{prefix} <@{row['user_id']}> — **{row['score']} pt{'s' if row['score'] != 1 else ''}**"
                    )
                period_embed = discord.Embed(
                    title=f"🏆 Fin de la Période {period['number']}",
                    description="\n".join(final_lines) if final_lines else "Aucun point marqué pendant cette période.",
                )
                next_period = await db.close_period_and_create_next(
                    round_row["guild_id"], period["id"]
                )
                if next_period:
                    period_embed.set_footer(text=f"La Période {next_period['number']} commence maintenant.")
                if isinstance(channel, discord.abc.Messageable):
                    await channel.send(embed=period_embed)

        await self.update_scoreboard(round_row["guild_id"])


bot = ScoreBot()


def game_channel_ok(interaction: discord.Interaction) -> bool:
    return config.game_channel_id is None or interaction.channel_id == config.game_channel_id


@bot.tree.command(name="aide", description="Afficher les commandes du jeu")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(await build_help_text(interaction), ephemeral=True)


@bot.tree.command(name="designer", description="Désigner manuellement le prochain meneur")
@app_commands.describe(joueur="Le membre à désigner")
async def designate(interaction: discord.Interaction, joueur: discord.Member):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    if await db.get_active_round(interaction.guild_id):
        await interaction.response.send_message("Impossible de changer de meneur tant que la manche n’est pas totalement clôturée.", ephemeral=True)
        return
    if not await db.is_participant_active(interaction.guild_id, joueur.id):
        await interaction.response.send_message("Ce membre n’est pas inscrit au jeu. Il doit d’abord utiliser `/participer`.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    # Le DM au nouveau meneur peut nécessiter des appels API Discord. On acquitte
    # la commande avant ces opérations pour éviter un timeout côté utilisateur.
    await interaction.response.defer()
    await db.set_master(interaction.guild_id, joueur.id, previous_master_id=state["current_master_id"])
    notified = await bot.notify_new_leader(interaction.guild_id, joueur.id)
    message = f"🎮 {joueur.mention} est le prochain meneur."
    if not notified:
        message += "\n⚠️ Impossible de lui envoyer les instructions en message privé."
    await interaction.followup.send(message)
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="meneur", description="Afficher le meneur actuel")
async def leader(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    if state["current_master_id"]:
        await interaction.response.send_message(f"🎮 Meneur actuel : <@{state['current_master_id']}>")
    else:
        await interaction.response.send_message("Aucun meneur n’est encore désigné.")


@bot.tree.command(name="lancer", description="Lancer la manche hebdomadaire")
@app_commands.describe(
    capture="Capture d’écran du jeu à deviner",
    url="URL publique d’une image à utiliser comme capture",
)
async def start(
    interaction: discord.Interaction,
    capture: discord.Attachment | None = None,
    url: str | None = None,
):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if capture is None and not (url and url.strip()):
        await interaction.response.send_message("Vous devez fournir soit une image, soit une URL d’image.", ephemeral=True)
        return
    if capture is not None and url and url.strip():
        await interaction.response.send_message("Choisissez soit une image, soit une URL d’image, pas les deux.", ephemeral=True)
        return
    if capture is not None and capture.content_type and not capture.content_type.startswith("image/"):
        await interaction.response.send_message("La capture doit être une image.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    if state["current_master_id"] != interaction.user.id:
        await interaction.response.send_message("Seul le meneur désigné peut lancer la manche.", ephemeral=True)
        return
    if await db.get_active_round(interaction.guild_id):
        await interaction.response.send_message("Une manche est déjà en cours ou en attente de validation finale.", ephemeral=True)
        return
    await interaction.response.send_modal(StartRoundModal(bot, capture=capture, image_url=(url or "").strip() or None))


@bot.tree.command(name="participer", description="S’inscrire au jeu")
async def join_game(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if await db.is_participant_active(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("✅ Tu participes déjà au jeu.", ephemeral=True)
        return

    await db.set_participant(interaction.guild_id, interaction.user.id, True)
    await interaction.response.send_message(
        "✅ Tu participes maintenant au jeu. Tu peux utiliser `/reponse` pendant les manches et tu es éligible aux tirages au sort.",
        ephemeral=True,
    )
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="quitter", description="Se désinscrire du jeu")
async def leave_game(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if not await db.is_participant_active(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("Tu n’es pas actuellement inscrit au jeu.", ephemeral=True)
        return

    state = await db.get_state(interaction.guild_id)
    if state["current_master_id"] == interaction.user.id:
        active_round = await db.get_active_round(interaction.guild_id)
        if active_round:
            await interaction.response.send_message(
                "Le meneur d’une manche en cours ne peut pas quitter le jeu avant sa clôture.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Tu es le prochain meneur. Utilise d’abord `/passe` avant de quitter le jeu.",
                ephemeral=True,
            )
        return

    await db.set_participant(interaction.guild_id, interaction.user.id, False)
    await interaction.response.send_message(
        "Tu ne participes plus au jeu. Tes scores et ton historique sont conservés, mais tu ne peux plus répondre ni être tiré au sort.",
        ephemeral=True,
    )
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="participants", description="Afficher les participants inscrits")
async def list_participants(interaction: discord.Interaction):
    if interaction.guild_id is None or interaction.guild is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return

    participant_ids = await db.active_participant_ids(interaction.guild_id)
    if not participant_ids:
        await interaction.response.send_message("Aucun participant n’est actuellement inscrit au jeu.")
        return

    state = await db.get_state(interaction.guild_id)
    current_master_id = state["current_master_id"]

    lines: list[str] = []
    for user_id in participant_ids:
        suffix = " — 🎮 **meneur**" if user_id == current_master_id else ""
        lines.append(f"<@{user_id}>{suffix}")

    embed = discord.Embed(
        title=f"👥 Participants inscrits — {len(participant_ids)}",
        description="\n".join(lines[:100]),
    )
    if len(lines) > 100:
        embed.set_footer(text=f"{len(lines) - 100} participant(s) supplémentaire(s) non affiché(s).")
    elif current_master_id:
        embed.set_footer(text="Le meneur actuel est indiqué dans la liste.")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="reponse", description="Envoyer une réponse secrète au meneur")
@app_commands.describe(reponse="Nom du jeu proposé")
async def answer(interaction: discord.Interaction, reponse: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if not await db.is_participant_active(interaction.guild_id, interaction.user.id):
        await interaction.response.send_message("Vous devez d’abord vous inscrire avec `/participer` pour pouvoir répondre.", ephemeral=True)
        return
    round_row = await db.get_open_round(interaction.guild_id)
    if not round_row:
        await interaction.response.send_message("Aucune manche n’est actuellement ouverte.", ephemeral=True)
        return
    if datetime.fromisoformat(round_row["ends_at"]) <= datetime.now(timezone.utc):
        await interaction.response.send_message("Le délai de réponse est terminé.", ephemeral=True)
        return
    if interaction.user.id == round_row["master_id"]:
        await interaction.response.send_message("Le meneur ne peut pas répondre à sa propre manche.", ephemeral=True)
        return
    if await db.user_has_correct_attempt(round_row["id"], interaction.user.id):
        await interaction.response.send_message("Tu as déjà trouvé le jeu pour cette manche.", ephemeral=True)
        return
    attempt_limit = round_row["attempt_limit"]
    if attempt_limit is not None:
        used_attempts = await db.user_attempt_count(round_row["id"], interaction.user.id)
        if used_attempts >= int(attempt_limit):
            await interaction.response.send_message(
                f"Tu as déjà utilisé tes **{attempt_limit} essais** pour cette manche.",
                ephemeral=True,
            )
            return

    answer_text = reponse.strip()
    if not answer_text:
        await interaction.response.send_message("La réponse ne peut pas être vide.", ephemeral=True)
        return
    if len(answer_text) > 200:
        await interaction.response.send_message("La réponse est limitée à 200 caractères.", ephemeral=True)
        return

    attempt_id = await db.create_attempt(
        interaction.guild_id, round_row["id"], interaction.user.id, answer_text
    )
    await interaction.response.send_message(
        "Réponse enregistrée. Le meneur va l’examiner et tu recevras son verdict en privé.",
        ephemeral=True,
    )
    await bot.notify_leader(round_row, attempt_id, interaction.user, answer_text)
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="passe", description="Passer la main et tirer un autre meneur")
async def pass_turn(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if await db.get_active_round(interaction.guild_id):
        await interaction.response.send_message("Impossible de passer la main tant que la manche n’est pas totalement clôturée.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    if state["current_master_id"] != interaction.user.id:
        await interaction.response.send_message("Seul le meneur désigné peut passer la main.", ephemeral=True)
        return
    excluded = {interaction.user.id}
    if state["previous_master_id"]:
        excluded.add(state["previous_master_id"])
    if interaction.guild is None:
        await interaction.response.send_message("Serveur Discord introuvable.", ephemeral=True)
        return

    # Le tirage peut déclencher fetch_member(). On acquitte l'interaction avant
    # le premier appel réseau potentiellement lent.
    await interaction.response.defer()
    new_master = await random_registered_participant(interaction.guild, excluded)
    if not new_master:
        await interaction.followup.send(
            "Aucun autre participant inscrit n’est éligible au tirage.",
            ephemeral=True,
        )
        return

    # Protection contre deux /passe reçus presque simultanément : seul le premier
    # peut remplacer le meneur qui a lancé la commande.
    changed = await db.compare_and_set_master(
        interaction.guild_id,
        expected_master_id=interaction.user.id,
        user_id=new_master,
        previous_master_id=state["previous_master_id"],
    )
    if not changed:
        await interaction.followup.send(
            "La main a déjà été passée ou le meneur a changé entre-temps.",
            ephemeral=True,
        )
        return

    notified = await bot.notify_new_leader(interaction.guild_id, new_master)
    message = (
        "🎮 **Nouveau meneur**\n"
        f"<@{new_master}> a été tiré au sort pour proposer la prochaine manche."
    )
    if not notified:
        message += "\n⚠️ Impossible de lui envoyer les instructions en message privé."
    await interaction.followup.send(message)
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="score", description="Afficher le classement d’une période")
@app_commands.describe(
    joueur="Joueur dont afficher les statistiques",
    periode="Numéro de période à consulter (période actuelle par défaut)",
)
async def score(
    interaction: discord.Interaction,
    joueur: discord.Member | None = None,
    periode: int | None = None,
):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return

    period = (
        await db.get_current_period(interaction.guild_id)
        if periode is None
        else await db.get_period_by_number(interaction.guild_id, periode)
    )
    if period is None:
        await interaction.response.send_message(f"La période {periode} n’existe pas.", ephemeral=True)
        return

    if joueur:
        stats = await db.user_stats(interaction.guild_id, joueur.id, period_id=period["id"])
        embed = discord.Embed(title=f"📊 Statistiques — {joueur.display_name} — Période {period['number']}")
        embed.add_field(name="Score", value=f"**{stats['score']}** point{'s' if stats['score'] != 1 else ''}", inline=True)
        embed.add_field(name="Classement", value=f"**#{stats['rank']}**" if stats['rank'] else "—", inline=True)
        embed.add_field(name="Manches jouées", value=str(stats['participations']), inline=True)
        embed.add_field(name="Réponses trouvées", value=str(stats['correct_rounds']), inline=True)
        embed.add_field(name="🥇 Premières places", value=str(stats['firsts']), inline=True)
        embed.add_field(name="🥈 Deuxièmes places", value=str(stats['seconds']), inline=True)
        embed.add_field(name="🥉 Troisièmes places", value=str(stats['thirds']), inline=True)
        embed.add_field(name="Manches proposées", value=str(stats['rounds_as_master']), inline=True)
        embed.add_field(name="Introuvables", value=str(stats['unfound']), inline=True)
        await interaction.response.send_message(embed=embed)
        return

    embed = await build_leaderboard_embed(interaction.guild_id, period_number=period["number"])
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="score-global", description="Afficher le classement toutes périodes confondues")
async def global_score(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    embed = await build_leaderboard_embed(interaction.guild_id, global_scores=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="periodes", description="Afficher les périodes de classement")
async def periods(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    await interaction.response.defer()
    # Une seule requête agrégée remplace l'ancien schéma N+1
    # (une requête supplémentaire par période).
    rows = await db.list_periods_with_progress(interaction.guild_id)
    if not rows:
        await interaction.followup.send("Aucune période n’est disponible.")
        return
    lines: list[str] = []
    for period in rows[:25]:
        progress = max(
            0,
            int(period["closed_round_count"] or 0)
            - int(period["round_count_offset"] or 0),
        )
        limit = period["round_limit"]
        if period["status"] == "active":
            suffix = f"en cours — {progress}/{limit} manches" if limit else "en cours — durée illimitée"
        else:
            suffix = "terminée"
        lines.append(f"**Période {period['number']}** — {suffix}")
    embed = discord.Embed(title="🗓️ Périodes de classement", description="\n".join(lines))
    embed.set_footer(text="Utilisez /score periode:N pour consulter le classement d’une période.")
    await interaction.followup.send(embed=embed)


period_group = app_commands.Group(name="periode", description="Configurer les périodes de classement")


@period_group.command(name="statut", description="Afficher la configuration des périodes")
async def period_status(interaction: discord.Interaction):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    period = await db.get_current_period(interaction.guild_id)
    progress, limit = await db.period_progress(period["id"])
    if limit is None:
        text = f"**Période {period['number']}** — renouvellement automatique : **jamais**."
    else:
        text = f"**Période {period['number']}** — renouvellement toutes les **{limit} manches**. Progression : **{progress}/{limit}**."
    await interaction.response.send_message(text, ephemeral=True)


@period_group.command(name="config", description="Configurer le renouvellement des périodes")
@app_commands.describe(mode="Jamais ou après un nombre de manches", manches="Nombre de manches pour une période")
@app_commands.choices(mode=[
    app_commands.Choice(name="Jamais", value="jamais"),
    app_commands.Choice(name="Nombre de manches", value="manches"),
])
async def period_config(
    interaction: discord.Interaction,
    mode: app_commands.Choice[str],
    manches: int | None = None,
):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    if mode.value == "jamais":
        await db.set_period_config(interaction.guild_id, None)
        await interaction.response.send_message("Les périodes n’ont désormais **aucune limite de manches**.", ephemeral=True)
    else:
        if manches is None or manches < 1 or manches > 1000:
            await interaction.response.send_message("Indique un nombre de manches compris entre 1 et 1000.", ephemeral=True)
            return
        await db.set_period_config(interaction.guild_id, manches)
        await interaction.response.send_message(
            f"La période actuelle se terminera après **{manches} nouvelles manches clôturées**. Les scores actuels sont conservés.",
            ephemeral=True,
        )
    await bot.update_scoreboard(interaction.guild_id)


bot.tree.add_command(period_group)


attempt_group = app_commands.Group(name="essais", description="Configurer le nombre d’essais par joueur")


@attempt_group.command(name="statut", description="Afficher la configuration des essais")
async def attempts_status(interaction: discord.Interaction):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    limit = state["default_attempt_limit"]
    text = "Essais par joueur : **illimités**." if limit is None else f"Essais par joueur : **{limit}** par manche."
    await interaction.response.send_message(text, ephemeral=True)


@attempt_group.command(name="config", description="Configurer le nombre d’essais par joueur")
@app_commands.describe(mode="Essais illimités ou nombre limité", nombre="Nombre d’essais par joueur")
@app_commands.choices(mode=[
    app_commands.Choice(name="Illimité", value="illimite"),
    app_commands.Choice(name="Nombre d’essais", value="nombre"),
])
async def attempts_config(
    interaction: discord.Interaction,
    mode: app_commands.Choice[str],
    nombre: int | None = None,
):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    if mode.value == "illimite":
        await db.set_attempt_config(interaction.guild_id, None)
        await interaction.response.send_message(
            "Le nombre d’essais est désormais **illimité** pour les prochaines manches.",
            ephemeral=True,
        )
    else:
        if nombre is None or nombre < 1 or nombre > 100:
            await interaction.response.send_message("Indique un nombre d’essais compris entre 1 et 100.", ephemeral=True)
            return
        await db.set_attempt_config(interaction.guild_id, nombre)
        await interaction.response.send_message(
            f"Chaque joueur disposera de **{nombre} essais** à partir de la prochaine manche.",
            ephemeral=True,
        )


bot.tree.add_command(attempt_group)


@bot.tree.command(name="corriger", description="Ajouter ou retirer des points")
@app_commands.describe(joueur="Joueur concerné", points="Valeur positive ou négative")
async def correct_score(interaction: discord.Interaction, joueur: discord.Member, points: int):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    if points == 0 or abs(points) > 100:
        await interaction.response.send_message("La correction doit être comprise entre -100 et +100, hors zéro.", ephemeral=True)
        return
    await db.add_score(interaction.guild_id, joueur.id, points, "manual_correction")
    await interaction.response.send_message(f"Score de {joueur.mention} corrigé de {points:+d} point(s).")
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="historique", description="Afficher les dernières manches terminées")
async def history(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    rows = await db.history(interaction.guild_id, 10)
    if not rows:
        await interaction.response.send_message("Aucune manche terminée.")
        return
    lines = [
        f"**#{row['id']}** — {row['solution']} — meneur <@{row['master_id']}>"
        for row in rows
    ]
    await interaction.response.send_message(embed=discord.Embed(title="Historique", description="\n".join(lines)))


@bot.tree.command(name="tableau", description="Créer ou actualiser le scoreboard permanent")
async def scoreboard_message(interaction: discord.Interaction):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message(
            "Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.",
            ephemeral=True,
        )
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message(
            "Utilise cette commande dans le canal du jeu afin d’y placer le scoreboard.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    # Si un ancien tableau est configuré, on essaie de le réutiliser.
    message = await bot.update_scoreboard(interaction.guild_id, create_if_missing=True)
    if message is None:
        await interaction.followup.send(
            "Impossible de créer le scoreboard. Vérifie que le bot peut voir le canal et y envoyer des messages.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Scoreboard permanent prêt : {message.jump_url}\nTu peux épingler ce message manuellement si tu le souhaites.",
        ephemeral=True,
    )


@bot.tree.command(name="reinitialiser", description="Remettre entièrement le jeu à zéro")
async def reset_game(interaction: discord.Interaction):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message(
            "Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        (
            "⚠️ **Réinitialisation complète**\n"
            "Cette action effacera les scores, l’historique, toutes les manches et tentatives, "
            "ainsi que le meneur actuel. Elle est irréversible.\n\n"
            "Le message de scoreboard permanent sera conservé mais remis à zéro."
        ),
        view=ResetConfirmView(interaction.user.id, bot),
        ephemeral=True,
    )


@bot.tree.command(name="cloturer", description="Clôturer immédiatement la manche en cours")
async def close_now(interaction: discord.Interaction):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    round_row = await db.get_active_round(interaction.guild_id)
    if not round_row:
        await interaction.response.send_message("Aucune manche en cours.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    finalized = await bot.lock_round_and_maybe_finish(round_row["id"])
    if finalized:
        await interaction.followup.send("Manche clôturée et résultats publiés.", ephemeral=True)
    else:
        await interaction.followup.send(
            "Les réponses sont maintenant fermées. La publication attend les validations restantes du meneur.",
            ephemeral=True,
        )


if __name__ == "__main__":
    bot.run(config.token)
