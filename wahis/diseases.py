"""The five monitored diseases, with separate poultry/non-poultry HPAI IDs."""

DISEASES = {
    'HPAI': 668,
    'ASF': 55,
    'LSD': 769,
    'FMD': 437,
    'HPAI_NON_POULTRY': 671,
    'BSE': 89,
}
DISEASE_NAMES = {
    'HPAI': 'High pathogenicity avian influenza viruses (Inf. with) (poultry)',
    'HPAI_NON_POULTRY': 'Influenza A viruses of high pathogenicity (Inf. with) (non-poultry including wild birds) (2017-)',
    'ASF': 'African swine fever virus (Inf. with)',
    'FMD': 'Foot and mouth disease virus (Inf. with)',
    'LSD': 'Lumpy skin disease virus (Inf. with)',
    'BSE': 'Bovine spongiform encephalopathy',
}


def require_supported_disease(name):
    """Accept official names with whitespace variations; reject unknown diseases."""
    if not isinstance(name, str) or ' '.join(name.split()) not in DISEASE_NAMES.values():
        raise ValueError(f'모니터링 대상 5종 이외의 질병은 저장하지 않습니다: {name!r}')


def selected_disease_ids(codes=None):
    selected = list(DISEASES) if codes is None else list(codes)
    # WAHIS treats an empty firstDiseases filter as ALL diseases.
    if not selected or any(code not in DISEASES for code in selected):
        raise ValueError('HPAI·ASF·FMD·LSD·BSE 중 하나 이상의 질병을 선택해야 합니다.')
    return [DISEASES[code] for code in dict.fromkeys(selected)]
