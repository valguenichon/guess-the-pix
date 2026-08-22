from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import load_config
from database import Database

BOT_VERSION = "0.7.3-reset"
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


def is_participant(member: discord.Member) -> bool:
    if not config.participant_role_ids:
        return True
    role_ids = {role.id for role in member.roles}
    return any(role_id in role_ids for role_id in config.participant_role_ids)


async def random_role_participant(guild: discord.Guild, excluded: set[int]) -> int | None:
    members = list(guild.members)
    if guild.member_count and len(members) < guild.member_count:
        try:
            members = [member async for member in guild.fetch_members(limit=None)]
        except (discord.Forbidden, discord.HTTPException):
            pass

    eligible = [
        member.id
        for member in members
        if not member.bot and member.id not in excluded and is_participant(member)
    ]
    return random.choice(eligible) if eligible else None


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

        await db.reset_guild(interaction.guild_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
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

    def __init__(self, bot: "ScoreBot", capture: discord.Attachment):
        super().__init__()
        self.bot = bot
        self.capture = capture

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

        now = datetime.now(timezone.utc)
        ends = now + timedelta(days=config.round_duration_days)
        round_id = await db.create_round(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            master_id=interaction.user.id,
            solution=str(self.solution).strip(),
            image_url=self.capture.url,
            started_at=now.isoformat(),
            ends_at=ends.isoformat(),
        )

        embed = discord.Embed(
            title=f"🎮 Manche #{round_id}",
            description=(
                f"Proposée par {interaction.user.mention}\n"
                f"Répondez anonymement avec **`/reponse réponse:`**.\n\n"
                f"Fin : <t:{int(ends.timestamp())}:F> — <t:{int(ends.timestamp())}:R>"
            ),
        )
        embed.set_image(url=self.capture.url)
        await interaction.response.send_message(embed=embed)
        await self.bot.update_scoreboard(interaction.guild_id)


class ScoreBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await db.init()
        logger.warning("Scoreboard bot version %s", BOT_VERSION)

        if config.guild_id:
            guild = discord.Object(id=config.guild_id)

            # Les commandes de ce bot doivent vivre uniquement sur ce serveur.
            # On copie d'abord les définitions courantes vers le serveur puis on
            # les synchronise. Cela remplace aussi les anciennes commandes de guilde.
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
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
            logger.warning(
                "Commandes globales synchronisees : %s",
                ", ".join(sorted(command.name for command in synced)),
            )

        self.close_due_rounds.start()

    async def build_scoreboard_embed(self, guild_id: int) -> discord.Embed:
        state = await db.get_state(guild_id)
        rows = await db.leaderboard(guild_id, limit=20)

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
            title="🏆 Scoreboard — Devine le jeu",
            description="\n".join(score_lines),
        )

        active_round = await db.get_active_round(guild_id)
        if active_round:
            if active_round["status"] == "open":
                participant_count = await db.round_participant_count(active_round["id"])
                round_text = (
                    f"**Manche #{active_round['id']} en cours**\n"
                    f"Meneur : <@{active_round['master_id']}>\n"
                    f"Fin : {discord_ts(active_round['ends_at'], 'F')} ({discord_ts(active_round['ends_at'], 'R')})\n"
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

        embed.add_field(name="État du jeu", value=round_text, inline=False)
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

        # Le verdict n’est visible que du meneur. On fige le message privé afin
        # d’éviter une seconde validation accidentelle et de garder un historique clair.
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

        try:
            player = await self.fetch_user(attempt["user_id"])
            await player.send(
                f"Ta réponse à la manche #{attempt['round_id']} a été examinée. "
                "Le résultat restera secret jusqu’à la clôture."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        refreshed = await db.get_attempt(int(raw_attempt_id))
        if refreshed and refreshed["round_status"] == "review":
            remaining = await db.pending_attempts(refreshed["round_id"])
            if not remaining:
                await self.finish_round(refreshed["round_id"])

    @tasks.loop(seconds=60)
    async def close_due_rounds(self) -> None:
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

        # On ferme d’abord pour éviter une double attribution par deux déclenchements concurrents.
        if not await db.close_round(round_id):
            return

        winners = list(await db.first_correct_by_user(round_id))
        podium = winners[:3]
        points = [3, 2, 1]
        for rank, row in enumerate(podium):
            await db.add_score(
                round_row["guild_id"],
                row["user_id"],
                points[rank],
                f"podium_{rank + 1}",
                round_id,
            )

        next_master: int | None = None
        next_master_reason: str
        if podium:
            next_master = podium[0]["user_id"]
            await db.set_master(
                round_row["guild_id"], next_master, previous_master_id=round_row["master_id"]
            )
            next_master_reason = f"🎮 <@{next_master}> devient le **prochain meneur**."
        else:
            await db.add_score(
                round_row["guild_id"],
                round_row["master_id"],
                2,
                "unfound_master_bonus",
                round_id,
            )
            guild = self.get_guild(round_row["guild_id"])
            next_master = (
                await random_role_participant(guild, excluded={round_row["master_id"]})
                if guild is not None
                else None
            )
            if next_master:
                await db.set_master(
                    round_row["guild_id"], next_master, previous_master_id=round_row["master_id"]
                )
                next_master_reason = (
                    f"🎲 Personne n’ayant trouvé, <@{next_master}> est **tiré au sort** "
                    "comme prochain meneur."
                )
            else:
                # Ne pas laisser le meneur sortant actif lorsqu’aucun tirage n’est possible.
                await db.clear_master(
                    round_row["guild_id"], previous_master_id=round_row["master_id"]
                )
                next_master_reason = (
                    "⚠️ Aucun autre membre ayant un rôle participant n’est éligible au tirage. "
                    "Un Admin du jeu doit utiliser `/designer`."
                )

        participant_count = await db.round_participant_count(round_id)
        attempt_count = await db.count_attempts(round_id)
        correct_count = len(winners)

        embed = discord.Embed(
            title=f"🏁 Résultats — Manche #{round_id}",
            description=f"La réponse était **{round_row['solution']}**.",
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Meneur de la manche",
            value=f"<@{round_row['master_id']}>",
            inline=False,
        )

        if podium:
            medals = ["🥇", "🥈", "🥉"]
            podium_lines = []
            for i, row in enumerate(podium):
                elapsed = format_elapsed(round_row["started_at"], row["submitted_at"])
                podium_lines.append(
                    f"{medals[i]} <@{row['user_id']}> — **+{points[i]} pt{'s' if points[i] > 1 else ''}** "
                    f"— trouvé en **{elapsed}**"
                )
            embed.add_field(name="Podium", value="\n".join(podium_lines), inline=False)
        else:
            embed.add_field(
                name="Introuvable",
                value=f"Personne n’a trouvé : <@{round_row['master_id']}> gagne **+2 points**.",
                inline=False,
            )

        other_correct = max(0, correct_count - len(podium))
        bilan_lines = [
            f"👥 **{participant_count}** participant{'s' if participant_count != 1 else ''}",
            f"💬 **{attempt_count}** tentative{'s' if attempt_count != 1 else ''}",
            f"✅ **{correct_count}** joueur{'s' if correct_count != 1 else ''} "
            f"{'ont' if correct_count != 1 else 'a'} trouvé",
        ]
        if other_correct:
            bilan_lines.append(
                f"👏 **{other_correct}** autre{'s' if other_correct != 1 else ''} bonne{'s' if other_correct != 1 else ''} "
                f"réponse{'s' if other_correct != 1 else ''} au-delà du podium"
            )
        embed.add_field(name="Bilan de la manche", value="\n".join(bilan_lines), inline=False)
        embed.add_field(name="Prochaine manche", value=next_master_reason, inline=False)

        if round_row["image_url"]:
            embed.set_image(url=round_row["image_url"])
        embed.set_footer(text="Les temps sont calculés depuis le lancement de la manche.")

        channel = self.get_channel(round_row["channel_id"])
        if channel is None:
            try:
                channel = await self.fetch_channel(round_row["channel_id"])
            except discord.HTTPException:
                channel = None
        if isinstance(channel, discord.abc.Messageable):
            await channel.send(embed=embed)

        await self.update_scoreboard(round_row["guild_id"])


bot = ScoreBot()


def game_channel_ok(interaction: discord.Interaction) -> bool:
    return config.game_channel_id is None or interaction.channel_id == config.game_channel_id


@bot.tree.command(name="aide", description="Afficher les commandes du jeu")
async def help_command(interaction: discord.Interaction):
    text = [
        "**Règles en bref**",
        "• Une manche dure **7 jours** : le meneur publie une capture.",
        "• Les réponses restent privées et sont validées par le meneur.",
        "• 🥇 **3 pts** · 🥈 **2 pts** · 🥉 **1 pt**, selon l’ordre des bonnes réponses.",
        "• Si personne ne trouve : **+2 pts au meneur**.",
        "• Le 1er devient meneur suivant ; s’il passe, tirage hors gagnant et meneur sortant. Sans gagnant, tirage hors meneur sortant.",
        "",
        "**Commandes joueurs**",
        "`/reponse réponse:` — proposer une réponse secrète",
        "`/score` — afficher le classement ; avec un joueur, afficher ses statistiques",
        "`/meneur` — afficher le meneur actuel",
        "`/historique` — afficher les dernières manches",
        "Les tirages utilisent automatiquement les deux rôles participants configurés.",
        "",
        "**Commandes du meneur**",
        "`/lancer capture:` — lancer une manche de 7 jours avec une capture",
        "`/passe` — passer la main avant de lancer la manche",
    ]
    if is_admin(interaction):
        text += [
            "",
            "**Administration**",
            "`/designer @joueur` — désigner le meneur",
            "`/corriger @joueur points:` — corriger le score",
            "`/cloturer` — clôturer immédiatement la manche",
            "`/tableau` — créer ou actualiser le scoreboard permanent",
            "`/reinitialiser` — remettre entièrement le jeu à zéro",
        ]
    await interaction.response.send_message("\n".join(text), ephemeral=True)


@bot.tree.command(name="designer", description="Désigner manuellement le prochain meneur")
@app_commands.describe(joueur="Le membre à désigner")
async def designate(interaction: discord.Interaction, joueur: discord.Member):
    if interaction.guild_id is None or not is_admin(interaction):
        await interaction.response.send_message("Commande réservée au rôle Admin du jeu ou aux administrateurs du serveur.", ephemeral=True)
        return
    if await db.get_active_round(interaction.guild_id):
        await interaction.response.send_message("Impossible de changer de meneur tant que la manche n’est pas totalement clôturée.", ephemeral=True)
        return
    if not is_participant(joueur):
        await interaction.response.send_message("Ce membre ne possède aucun des rôles participants configurés.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    await db.set_master(interaction.guild_id, joueur.id, previous_master_id=state["current_master_id"])
    await interaction.response.send_message(f"🎮 {joueur.mention} est le prochain meneur.")
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
@app_commands.describe(capture="Capture d’écran du jeu à deviner")
async def start(interaction: discord.Interaction, capture: discord.Attachment):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if capture.content_type and not capture.content_type.startswith("image/"):
        await interaction.response.send_message("La capture doit être une image.", ephemeral=True)
        return
    state = await db.get_state(interaction.guild_id)
    if state["current_master_id"] != interaction.user.id:
        await interaction.response.send_message("Seul le meneur désigné peut lancer la manche.", ephemeral=True)
        return
    if await db.get_active_round(interaction.guild_id):
        await interaction.response.send_message("Une manche est déjà en cours ou en attente de validation finale.", ephemeral=True)
        return
    await interaction.response.send_modal(StartRoundModal(bot, capture))


@bot.tree.command(name="reponse", description="Envoyer une réponse secrète au meneur")
@app_commands.describe(reponse="Nom du jeu proposé")
async def answer(interaction: discord.Interaction, reponse: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if not game_channel_ok(interaction):
        await interaction.response.send_message("Cette commande doit être utilisée dans le canal du jeu.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member) or not is_participant(interaction.user):
        await interaction.response.send_message("Cette commande est réservée aux membres ayant un rôle participant.", ephemeral=True)
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
        "Réponse enregistrée. Le meneur va l’examiner ; son verdict ne sera pas révélé avant la fin de la manche.",
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
    new_master = await random_role_participant(interaction.guild, excluded)
    if not new_master:
        await interaction.response.send_message(
            "Aucun autre membre ayant un rôle participant n’est éligible au tirage.",
            ephemeral=True,
        )
        return
    await db.set_master(
        interaction.guild_id, new_master, previous_master_id=state["previous_master_id"]
    )
    await interaction.response.send_message(f"🎲 Nouveau meneur tiré au sort : <@{new_master}>")
    await bot.update_scoreboard(interaction.guild_id)


@bot.tree.command(name="score", description="Afficher le classement général")
async def score(interaction: discord.Interaction, joueur: discord.Member | None = None):
    if interaction.guild_id is None:
        await interaction.response.send_message("Commande disponible uniquement sur le serveur.", ephemeral=True)
        return
    if joueur:
        stats = await db.user_stats(interaction.guild_id, joueur.id)
        embed = discord.Embed(title=f"📊 Statistiques — {joueur.display_name}")
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
    rows = await db.leaderboard(interaction.guild_id)
    if not rows:
        await interaction.response.send_message("Le classement est encore vide.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, row in enumerate(rows):
        prefix = medals[i] if i < 3 else f"**{i + 1}.**"
        lines.append(f"{prefix} <@{row['user_id']}> — **{row['score']} pt{'s' if row['score'] != 1 else ''}**")
    await interaction.response.send_message(embed=discord.Embed(title="🏆 Scoreboard", description="\n".join(lines)))


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
