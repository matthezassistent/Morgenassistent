def is_unanswered(messages: List[dict]) -> bool:
    if not messages:
        return False

    last_msg = messages[-1]
    headers = last_msg.get("payload", {}).get("headers", [])
    from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
    snippet = last_msg.get("snippet", "")

    # Multilinguale Frageindikatoren
    question_keywords = [
        "?", "kannst du", "würden sie", "bitte", "könntest du", "was ist", "wann", "wie", "wo", "warum", "soll ich",
        "can you", "could you", "please", "would you", "what is", "when", "how", "where", "why", "should I",
        "kun je", "zou je", "alsjeblieft", "wat is", "wanneer", "hoe", "waar", "waarom", "moet ik"
    ]

    snippet_lower = snippet.lower()
    from_header_lower = from_header.lower()

    # System-/Newsletter-Mails erkennen und ausschließen
    newsletter_phrases = [
        "to unsubscribe", "automated message", "you are receiving this", "no reply needed",
        "nicht antworten", "automatisch generiert", "du erhältst diese nachricht", "abmelden",
        "keine antwort erforderlich", "benachrichtigungseinstellungen", "email-einstellungen",
        "ihre email wurde hinterlegt", "sie erhalten diese e-mail", "rufen sie das portal auf",
        "please do not reply to this email", "chess.com customer support", "update your notification settings",
        "this email was sent to", "download on the app store", "get it on google play",
        "game in pgn format", "chess.com", "let's play", "link to game",
        "ticket-id", "passwort reset", "pdf ist bereit", "csv ist bereit",
        "aktualisierte einladung", "bestätige deine transaktion", "termin abgesagt",
        "einladung", "livestream", "transaction", "support", "kundenservice",
        "dies ist keine antwortadresse", "kalendereinladung", "meeting invitation"
    ]
    for phrase in newsletter_phrases:
        if phrase in snippet_lower:
            print(f"🛑 Gefiltert durch Stichwort '{phrase}' im Snippet: {snippet_lower[:100]}")
            return False

    if any(service in from_header_lower for service in ["calendar", "no-reply", "noreply", "donotreply"]):
        print(f"🛑 Gefiltert durch Absender '{from_header_lower}'")
        return False

    # Prüfe, ob Mail von mir oder an mich
    is_sent_by_me = "SENT" in last_msg.get("labelIds", [])
    contains_question = any(kw in snippet_lower for kw in question_keywords)

    # Fall 1: eingegangene Mail, nicht von mir, Frage enthalten
    if not is_sent_by_me:
        return contains_question

    # Fall 2: gesendete Mail, letzte Nachricht von mir → keine Antwort erhalten
    if is_sent_by_me:
        if len(messages) > 1 and messages[-1] == messages[-1]:
            return contains_question

    return False
