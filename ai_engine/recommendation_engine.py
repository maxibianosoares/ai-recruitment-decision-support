def get_recommendation(score):

    if score >= 80:
        return "Highly Recommended"

    elif score >= 60:
        return "Recommended"

    elif score >= 40:
        return "Needs Further Review"

    else:
        return "Not Recommended"