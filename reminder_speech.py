
"""Format reminder dates and times for natural speech output."""

def format_spoken_reminder(due_local):
    """Convert a local reminder datetime into conversational speech."""
    hours = (
        "twelve", "one", "two", "three", "four", "five",
        "six", "seven", "eight", "nine", "ten", "eleven"
    )
    numbers = (
        "zero", "one", "two", "three", "four", "five",
        "six", "seven", "eight", "nine", "ten", "eleven",
        "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen"
    )
    tens = ("", "", "twenty", "thirty", "forty", "fifty")

    ordinal_days = (
        "first", "second", "third", "fourth", "fifth",
        "sixth", "seventh", "eighth", "ninth", "tenth",
        "eleventh", "twelfth", "thirteenth", "fourteenth",
        "fifteenth", "sixteenth", "seventeenth",
        "eighteenth", "nineteenth", "twentieth",
        "twenty first", "twenty second", "twenty third",
        "twenty fourth", "twenty fifth", "twenty sixth",
        "twenty seventh", "twenty eighth", "twenty ninth",
        "thirtieth", "thirty first"
    )

    spoken_date = (
        f"{due_local.strftime('%B')} "
        f"{ordinal_days[due_local.day - 1]}"
    )

    hour_text = hours[due_local.hour % 12]
    minute = due_local.minute

    if minute == 0:
        spoken_time = f"{hour_text} o'clock"
    elif minute < 10:
        spoken_time = f"{hour_text} oh {numbers[minute]}"
    elif minute < 20:
        spoken_time = f"{hour_text} {numbers[minute]}"
    else:
        minute_text = tens[minute // 10]
        if minute % 10:
            minute_text += f" {numbers[minute % 10]}"
        spoken_time = f"{hour_text} {minute_text}"

    if 5 <= due_local.hour < 12:
        spoken_time += " in the morning"
    elif 12 <= due_local.hour < 17:
        spoken_time += " in the afternoon"
    elif 17 <= due_local.hour < 21:
        spoken_time += " in the evening"
    else:
        spoken_time += " at night"

    return f"{spoken_date} at {spoken_time}"
