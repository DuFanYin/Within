"""
Manually crafted seed rows — no generation loops.

Tuple shape:
  (days_ago, hour_utc, mode, role, content, source, session_id,
   valence, intensity, category, sub_tags)

Assistant rows: valence/intensity/category None, sub_tags [].
Voice rows: content is placeholder text (no audio_files row).
"""

# fmt: off
RECORDS: list[tuple] = [
    # ══ ~90 days ago — late summer, new routine ═══════════════════════════════
    (88, 9, "journal", "user",
     "Last week of summer before the semester. I keep telling myself I'll rest but I spent the day organizing folders instead of actually resting.",
     "text", None, 0.15, 0.4, "positive", ["content", "relaxed"]),

    (85, 20, "journal", "user",
     "Dinner with my parents. They asked what I'm doing with my life in that gentle way that still lands like a quiz.",
     "text", None, -0.35, 0.55, "social", ["ashamed", "overlooked"]),

    (85, 21, "chat", "user",
     "Why do I leave family dinners feeling smaller than when I arrived?",
     "text", "s0", -0.4, 0.6, "social", ["lonely", "ashamed"]),
    (85, 21, "chat", "assistant",
     "Sometimes the people who love us most still measure us with rulers we didn't choose. What part of tonight felt most like shrinking?",
     "text", "s0", None, None, None, []),

    # ══ ~75 days — early autumn stress building ═══════════════════════════════
    (78, 8, "journal", "user",
     "First real deadline of the term. Stayed up until two rewriting something that was probably fine at midnight.",
     "text", None, -0.45, 0.7, "stress", ["exhausted", "time_crunched"]),

    (75, 14, "journal", "user",
     "Walked the long way home without headphones. Noticed the air cooling down. Felt like my brain unclenched a little.",
     "text", None, 0.4, 0.35, "positive", ["relaxed", "content"]),

    (72, 7, "journal", "user",
     "Sunday with nothing scheduled and I still couldn't enjoy it. Kept waiting for the guilt to justify doing nothing.",
     "text", None, -0.5, 0.55, "low_mood", ["empty", "unmotivated"]),

    (72, 19, "chat", "user",
     "Is it normal to feel lonely on a day when nobody needed anything from me?",
     "text", "s0b", -0.35, 0.5, "social", ["lonely"]),

    # ══ ~60 days — mid-term crunch ════════════════════════════════════════════
    (68, 10, "journal", "user",
     "Presentation today. Hands shook during the first slide but I got through it. Nobody mentioned it afterward which was either kind or they didn't notice.",
     "text", None, -0.25, 0.65, "anxiety", ["tense", "worried"]),

    (65, 18, "journal", "user",
     "A friend texted to check in unprompted. I almost cried in the stairwell. I didn't realize how long I'd been running on empty.",
     "text", None, 0.55, 0.5, "positive", ["happy", "content"]),

    (62, 11, "journal", "user",
     "Took the afternoon off without asking permission from anyone. Sat in the park and watched dogs. Simple but it reset something.",
     "text", None, 0.6, 0.45, "positive", ["relaxed", "happy"]),

    (58, 22, "journal", "user",
     "Roommate left dishes again. I cleaned them and then resentfully catalogued every other small thing they've done this month.",
     "text", None, -0.6, 0.75, "anger", ["irritable", "offended"]),

  # ── Day 55 — skipped ────────────────────────────────────────────────────────

    (52, 9, "journal", "user",
     "Group project meeting. I did most of the talking and most of the worrying. Came home feeling like the only adult in the room.",
     "text", None, -0.4, 0.7, "stress", ["overwhelmed", "busy"]),

    (48, 16, "journal", "user",
     "Scrolled for an hour looking for proof that other people struggle too. Found it. Didn't feel better afterward.",
     "text", None, -0.45, 0.6, "social", ["comparison_anxiety", "lonely"]),

    (45, 8, "journal", "user",
     "Woke up already tired. Coffee didn't help. The whole day felt like wading through syrup.",
     "text", None, -0.55, 0.65, "low_mood", ["exhausted", "helpless"]),

    (45, 20, "chat", "user",
     "I don't think I'm depressed. I think I'm just tired in a way sleep doesn't fix.",
     "text", "s0c", -0.4, 0.55, "low_mood", ["empty", "lost"]),
    (45, 20, "chat", "assistant",
     "That distinction matters. Chronic depletion can look like low mood without being a label. What drained you most this week?",
     "text", "s0c", None, None, None, []),

    (42, 13, "journal", "user",
     "Cleared my inbox for the first time in weeks. Ridiculously proud of something that should be baseline.",
     "text", None, 0.35, 0.4, "positive", ["accomplished", "content"]),

    (38, 19, "journal", "user",
     "Called in sick even though I wasn't sick—just couldn't face another meeting about meetings.",
     "text", None, -0.3, 0.6, "stress", ["drained", "overwhelmed"]),

    (35, 10, "journal", "user",
     "Started a notes doc called 'things that are actually fine' and only wrote one line before abandoning it. Still counts maybe.",
     "text", None, 0.1, 0.35, "anxiety", ["uneasy"]),

    # ══ ~30 days — existing arc (anxious return, stress, social, recovery) ═══
    (30, 8, "journal", "user",
     "First day back after the holiday. Inbox was a disaster. Couldn't focus for more than ten minutes at a time. Why do vacations always make re-entry harder?",
     "text", None, -0.5, 0.65, "anxiety", ["worried", "uneasy"]),

    (30, 18, "chat", "user",
     "I always feel like I'm behind. Like everyone else just naturally keeps up and I'm always catching up.",
     "text", "s1", -0.45, 0.6, "anxiety", ["out_of_control", "future_anxiety"]),
    (30, 18, "chat", "assistant",
     "That feeling of constantly catching up is exhausting. Do you think it's really true, or is it the story your brain tells you when you're overwhelmed?",
     "text", "s1", None, None, None, []),

    (28, 9, "journal", "user",
     "Three meetings before lunch. By noon I was already running on empty. Skipped the gym. Ate at my desk. Classic.",
     "text", None, -0.4, 0.7, "stress", ["exhausted", "drained"]),

    (28, 17, "chat", "user",
     "I said yes to too many things again this week and now I'm drowning.",
     "text", "s2", -0.5, 0.75, "stress", ["overwhelmed", "time_crunched"]),
    (28, 17, "chat", "assistant",
     "Drowning in commitments you chose — there's a particular guilt that comes with that. What's the one thing you could drop this week without real consequences?",
     "text", "s2", None, None, None, []),
    (28, 17, "chat", "user",
     "Probably the Friday sync. No one actually needs it.",
     "text", "s2", 0.1, 0.4, "stress", ["busy"]),

    (27, 7, "journal", "user",
     "Didn't want to get out of bed. Just lay there listening to the rain. Eventually did, but it felt like moving through water all day.",
     "text", None, -0.65, 0.6, "low_mood", ["helpless", "unmotivated"]),

    (27, 8, "journal", "user",
     "Tried to journal in the morning but nothing came out. Just stared at the page. Sometimes silence is the only honest thing.",
     "voice", None, -0.55, 0.5, "low_mood", ["empty", "lost"]),

  # ── Days 25–24 skipped ───────────────────────────────────────────────────────

    (23, 19, "chat", "user",
     "Had dinner with old friends. Everyone seemed to have it together — promotions, relationships, apartments they actually own. I smiled through the whole thing.",
     "text", "s3", -0.55, 0.7, "social", ["jealous", "comparison_anxiety"]),
    (23, 19, "chat", "assistant",
     "Performing okay when you don't feel it takes a toll. What was the moment during dinner you felt most distant from the conversation?",
     "text", "s3", None, None, None, []),
    (23, 19, "chat", "user",
     "When they started talking about buying property. I just… checked out internally.",
     "text", "s3", -0.4, 0.55, "social", ["lonely", "overlooked"]),

    (23, 22, "journal", "user",
     "Came home and sat in the dark for a bit. Not sad exactly. Just needed to decompress from all the performing.",
     "text", None, -0.3, 0.45, "low_mood", ["empty"]),

    (21, 8, "journal", "user",
     "Woke up before the alarm. Made proper breakfast. Small wins.",
     "text", None, 0.3, 0.35, "positive", ["content"]),

  # ── Day 20 skipped ────────────────────────────────────────────────────────────

    (19, 15, "chat", "user",
     "I finally finished the project I've been dragging for a month. Submitted it this afternoon. I feel… lighter.",
     "text", "s4", 0.75, 0.65, "positive", ["accomplished", "relaxed"]),
    (19, 15, "chat", "assistant",
     "That lightness is real — you earned it. What made you able to push through today?",
     "text", "s4", None, None, None, []),
    (19, 15, "chat", "user",
     "I just started. Stopped waiting to be in the mood.",
     "text", "s4", 0.6, 0.5, "positive", ["accomplished"]),

    (19, 18, "journal", "user",
     "Went for a run after submitting. The city felt different — like I had space in my chest again.",
     "text", None, 0.7, 0.55, "positive", ["happy", "relaxed"]),

    (17, 11, "journal", "user",
     "My manager publicly credited someone else for my work in the all-hands. I didn't say anything. I should have.",
     "text", None, -0.7, 0.8, "anger", ["unfair", "offended"]),

    (17, 21, "chat", "user",
     "I'm furious but I keep it so contained that no one even knows. Is that healthy?",
     "voice", "s5", -0.65, 0.75, "anger", ["suppressed_anger", "irritable"]),
    (17, 21, "chat", "assistant",
     "Contained anger isn't the same as resolved anger. It tends to leak. Is there a safe place you could let some of it out — even just on paper?",
     "text", "s5", None, None, None, []),

  # ── Days 15–14 skipped ──────────────────────────────────────────────────────

    (13, 10, "journal", "user",
     "Quiet Saturday. Made coffee, read for two hours, didn't check my phone until noon. I'd forgotten what that felt like.",
     "text", None, 0.5, 0.4, "positive", ["relaxed", "content"]),

    (12, 9, "chat", "user",
     "Performance review next week. I've been dreading it for a month. What if they've been disappointed in me this whole time and just never said?",
     "text", "s6", -0.6, 0.8, "anxiety", ["worried", "future_anxiety"]),
    (12, 9, "chat", "assistant",
     "That anticipatory dread is often worse than the thing itself. What's the most realistic outcome you can imagine — not worst-case, not best?",
     "text", "s6", None, None, None, []),
    (12, 9, "chat", "user",
     "Probably fine. My manager seemed okay last week. I just spiral.",
     "text", "s6", -0.1, 0.5, "anxiety", ["uneasy"]),

    (12, 22, "journal", "user",
     "Can't stop rehearsing the review conversation in my head. Different versions. All of them bad.",
     "voice", None, -0.5, 0.7, "anxiety", ["out_of_control", "worried"]),

    (10, 14, "chat", "user",
     "Review went well. Better than I expected. My manager said I've been 'quietly indispensable.' I didn't know what to do with that.",
     "text", "s7", 0.7, 0.6, "positive", ["accomplished", "content"]),
    (10, 14, "chat", "assistant",
     "Quietly indispensable — that's a real compliment. How did it land for you in the moment?",
     "text", "s7", None, None, None, []),
    (10, 14, "chat", "user",
     "I said thank you and then immediately worried it was a backhanded way of saying I'm not visible enough.",
     "text", "s7", 0.2, 0.45, "anxiety", ["uneasy"]),

    (8, 16, "journal", "user",
     "Called my sister for no reason. Just talked for an hour about nothing. I needed that more than I realized.",
     "text", None, 0.65, 0.55, "positive", ["happy", "content"]),

  # ── Day 6 skipped ─────────────────────────────────────────────────────────────

    (5, 18, "companion", "user",
     "I feel like I'm always managing other people's emotions and nobody manages mine.",
     "text", "s8", -0.55, 0.7, "social", ["lonely", "overlooked"]),
    (5, 18, "companion", "assistant",
     "Being the one who holds space for everyone else is quietly depleting. When did you last let someone hold space for you?",
     "text", "s8", None, None, None, []),
    (5, 18, "companion", "user",
     "I don't know. Maybe never. I don't think I know how to let that happen.",
     "text", "s8", -0.4, 0.6, "social", ["lonely"]),

    (5, 21, "journal", "user",
     "Long week. Didn't exercise once. Ate badly. Slept badly. The whole package.",
     "text", None, -0.45, 0.65, "stress", ["exhausted", "drained"]),

    (3, 12, "journal", "user",
     "Took myself out for lunch alone. Sat by the window and watched people. Felt oddly peaceful.",
     "text", None, 0.45, 0.4, "positive", ["relaxed", "content"]),

    (3, 20, "companion", "user",
     "I've been thinking — I spend a lot of energy trying not to be a burden. But maybe that's its own kind of distance.",
     "voice", "s9", -0.2, 0.55, "social", ["lonely", "ashamed"]),
    (3, 20, "companion", "assistant",
     "That's a real insight. Protecting people from your needs is a form of walls. What would it feel like to need something openly?",
     "text", "s9", None, None, None, []),

    (1, 3, "journal", "user",
     "Couldn't sleep. 3am thoughts. The kind that feel very urgent and very stupid at the same time.",
     "text", None, -0.4, 0.6, "anxiety", ["uneasy", "out_of_control"]),

    (0, 10, "companion", "user",
     "Not sad exactly. Just quiet inside. Like the volume got turned down on everything.",
     "text", "s10", -0.2, 0.4, "low_mood", ["empty", "lost"]),
    (0, 10, "companion", "assistant",
     "Sometimes quiet isn't emptiness — it's the mind asking for rest. Are you giving yourself permission to just be still today?",
     "text", "s10", None, None, None, []),
    (0, 10, "companion", "user",
     "I'm trying to.",
     "text", "s10", 0.1, 0.3, "positive", ["relaxed"]),
]
# fmt: on
