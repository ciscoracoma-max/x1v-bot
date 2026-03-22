import discord
import os
import re
from datetime import datetime, timezone

from discord.ext import commands
from discord import app_commands

# =========================
# CONFIG
# =========================
GUILD_ID = 948971532431015976
CONFIG_CHANNEL_ID = 1478282165618737266
VOUCHES_CHANNEL_ID = 1478334777533927456
ADMIN_ID = 458624557763526666

APPROVE_EMOJI = "✅"
DECLINE_EMOJI = "❌"

SHOP_NAME = "v1xclusive"
EMBED_COLOR_REVIEW = 0x5865F2
EMBED_COLOR_APPROVED = 0xF1C40F
EMBED_COLOR_DECLINED = 0xE74C3C
EMBED_COLOR_SUCCESS = 0x2ECC71

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("Missing TOKEN environment variable.")

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# HELPERS
# =========================
def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def review_already_handled(embed: discord.Embed) -> bool:
    if not embed.title:
        return False
    lowered = embed.title.lower()
    return "approved" in lowered or "declined" in lowered or "rejected" in lowered

def get_field_value(embed: discord.Embed, field_name: str, default: str = "N/A") -> str:
    for field in embed.fields:
        if field.name.strip().lower() == field_name.strip().lower():
            return field.value
    return default

async def get_next_vouch_number(vouches_channel: discord.TextChannel) -> int:
    async for msg in vouches_channel.history(limit=25):
        if not msg.embeds:
            continue
        embed = msg.embeds[0]
        for field in embed.fields:
            if field.name.strip().lower() in {"vouch n°", "vouch no", "vouch number"}:
                match = re.search(r"\d+", field.value)
                if match:
                    return int(match.group()) + 1
    return 1

def make_review_embed(
    user: discord.User | discord.Member,
    service: str,
    review: str,
    stars: int,
    proof_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{SHOP_NAME} - New vouch submitted for review",
        color=EMBED_COLOR_REVIEW,
        timestamp=utc_now(),
    )
    embed.description = "⭐" * stars
    embed.add_field(name="Vouch", value=review, inline=False)
    embed.add_field(name="Service", value=service, inline=False)
    embed.add_field(name="Submitted by", value=user.mention, inline=True)
    embed.add_field(name="User ID", value=str(user.id), inline=True)

    if proof_url:
        embed.set_image(url=proof_url)

    embed.set_footer(text="React with ✅ to approve or ❌ to decline")
    return embed

def make_public_vouch_embed(
    stars_display: str,
    vouch_text: str,
    service: str,
    submitted_by: str,
    vouch_number: int,
    proof_url: str | None = None,
) -> discord.Embed:
    approved_at = utc_now()

    embed = discord.Embed(
        title=f"{SHOP_NAME} - Thank you for submitting a vouch!",
        color=EMBED_COLOR_APPROVED,
        timestamp=approved_at,
    )
    embed.description = stars_display
    embed.add_field(name="Vouch", value=vouch_text, inline=False)
    embed.add_field(name="Service", value=service, inline=False)
    embed.add_field(name="Vouch N°", value=str(vouch_number), inline=True)
    embed.add_field(name="Vouched by", value=submitted_by, inline=True)
    embed.add_field(
        name="Vouched at",
        value=approved_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        inline=True,
    )

    if proof_url:
        embed.set_image(url=proof_url)

    embed.set_footer(text=f"{SHOP_NAME} • Approved")
    return embed

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")

    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"Command sync failed: {e}")

# =========================
# SLASH COMMAND
# =========================
@bot.tree.command(name="vouch", description="Submit a vouch for approval.")
@app_commands.describe(
    service="What was bought or done",
    review="The review/vouch text",
    stars="Stars from 1 to 5",
    proof="Optional image proof"
)
async def vouch(
    interaction: discord.Interaction,
    service: str,
    review: str,
    stars: app_commands.Range[int, 1, 5],
    proof: discord.Attachment | None = None,
):
    if interaction.guild_id != GUILD_ID:
        await interaction.response.send_message(
            "This command only works in the configured server.",
            ephemeral=True,
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "This command must be used in the server.",
            ephemeral=True,
        )
        return

    config_channel = interaction.guild.get_channel(CONFIG_CHANNEL_ID)
    if config_channel is None:
        await interaction.response.send_message(
            "Config/review channel not found.",
            ephemeral=True,
        )
        return

    proof_url = None
    if proof is not None:
        allowed = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        if not proof.filename.lower().endswith(allowed):
            await interaction.response.send_message(
                "Proof must be an image file: png, jpg, jpeg, webp, or gif.",
                ephemeral=True,
            )
            return
        proof_url = proof.url

    embed = make_review_embed(
        user=interaction.user,
        service=service,
        review=review,
        stars=stars,
        proof_url=proof_url,
    )

    review_message = await config_channel.send(embed=embed)
    await review_message.add_reaction(APPROVE_EMOJI)
    await review_message.add_reaction(DECLINE_EMOJI)

    await interaction.response.send_message(
        f"Your vouch has been sent for approval in **{SHOP_NAME}**.",
        ephemeral=True,
    )

vouch = app_commands.guilds(discord.Object(id=GUILD_ID))(vouch)

# =========================
# REACTION APPROVAL FLOW
# =========================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if payload.channel_id != CONFIG_CHANNEL_ID:
        return

    if payload.user_id != ADMIN_ID:
        return

    emoji = str(payload.emoji)
    if emoji not in (APPROVE_EMOJI, DECLINE_EMOJI):
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    channel = guild.get_channel(payload.channel_id)
    if channel is None:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    if not message.embeds:
        return

    review_embed = message.embeds[0]

    if review_already_handled(review_embed):
        return

    stars_display = review_embed.description or "⭐"
    vouch_text = get_field_value(review_embed, "Vouch", "No review text provided.")
    service = get_field_value(review_embed, "Service", "Not specified")
    submitted_by = get_field_value(review_embed, "Submitted by", "Unknown")
    proof_url = review_embed.image.url if review_embed.image and review_embed.image.url else None

    if emoji == DECLINE_EMOJI:
        declined_embed = discord.Embed(
            title="Vouch Declined",
            description=f"Declined by <@{ADMIN_ID}>",
            color=EMBED_COLOR_DECLINED,
            timestamp=utc_now(),
        )
        await message.edit(embed=declined_embed)
        try:
            await message.clear_reactions()
        except discord.Forbidden:
            pass
        return

    if emoji == APPROVE_EMOJI:
        vouches_channel = guild.get_channel(VOUCHES_CHANNEL_ID)
        if vouches_channel is None:
            return

        vouch_number = await get_next_vouch_number(vouches_channel)

        final_embed = make_public_vouch_embed(
            stars_display=stars_display,
            vouch_text=vouch_text,
            service=service,
            submitted_by=submitted_by,
            vouch_number=vouch_number,
            proof_url=proof_url,
        )

        await vouches_channel.send(embed=final_embed)

        approved_embed = discord.Embed(
            title="Vouch Approved",
            description=f"Approved by <@{ADMIN_ID}>\nPosted in <#{VOUCHES_CHANNEL_ID}>",
            color=EMBED_COLOR_SUCCESS,
            timestamp=utc_now(),
        )
        await message.edit(embed=approved_embed)
        try:
            await message.clear_reactions()
        except discord.Forbidden:
            pass

# =========================
# ERROR HANDLER
# =========================
@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Slash command error: {error}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong while running that command.", ephemeral=True)
        else:
            await interaction.response.send_message("Something went wrong while running that command.", ephemeral=True)
    except Exception:
        pass

bot.run(TOKEN)
