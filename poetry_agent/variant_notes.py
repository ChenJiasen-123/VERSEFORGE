"""Supplemental glyph evidence without silently selecting contextual readings."""
def variant_note(character):
    if character != '暖':
        return None
    return {'related_character':'煖',
            'source':'https://dict.variants.moe.edu.tw/dictView.jsp?ID=20079&q=1',
            'reading_source':'https://dict.variants.moe.edu.tw/dictView.jsp?ID=62803',
            'relationship':'attested_variant',
            'reading_labels':['nuǎn','xuān'],
            'context_selected':False,
            'limitation':'候选字形与多读音依据；不将摘录中已见部属自动当作本字全部读音。'}
