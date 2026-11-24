"""Conservative revision selection; model consensus is not quality proof."""

def compliance_repair_priority(before,after,hard_issues):
    """Only a confirmed repair outranks aesthetic preference, never mere uncertainty."""
    known_problem=bool(before.get('violations') or before.get('repair_requests'))
    return bool(known_problem and after.get('complete') and after.get('confirmed') and not hard_issues)

def select_revision(original, revised, *, hard_issues, requirements, literary_review, comparison):
    reasons=[]
    if hard_issues:
        reasons.append('hard_constraints_failed')
    if not requirements.get('complete') or not requirements.get('confirmed'):
        reasons.append('requirements_not_confirmed')
    assessment=literary_review.get('assessment',{})
    if assessment.get('decision')!='keep':
        reasons.append('literary_review_not_keep')
    if (comparison.get('selection_status')!='consensus'
            or comparison.get('order_consistent') is not True
            or comparison.get('assessment',{}).get('choice')!='b'):
        reasons.append('revision_preference_not_confirmed')
    adopted=not reasons
    return {'poem':revised if adopted else original,'adopted':adopted,
            'reasons':reasons,'selection_protocol':'editor-selection-0.1',
            'quality_verified':False,'requires_human_review':False}
