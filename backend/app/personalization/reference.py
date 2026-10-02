"""Reference data for normalising personal facts: countries, languages, currencies.

Kept in code (not fetched) so validation is deterministic and works offline. Countries use
ISO 3166-1 alpha-3, which is also what passports print in their machine-readable zone.
"""

from __future__ import annotations

import re
import unicodedata

_COUNTRIES = """
AFG Afghanistan
ALA Åland Islands
ALB Albania
DZA Algeria
ASM American Samoa
AND Andorra
AGO Angola
AIA Anguilla
ATA Antarctica
ATG Antigua and Barbuda
ARG Argentina
ARM Armenia
ABW Aruba
AUS Australia
AUT Austria
AZE Azerbaijan
BHS Bahamas
BHR Bahrain
BGD Bangladesh
BRB Barbados
BLR Belarus
BEL Belgium
BLZ Belize
BEN Benin
BMU Bermuda
BTN Bhutan
BOL Bolivia
BES Bonaire, Sint Eustatius and Saba
BIH Bosnia and Herzegovina
BWA Botswana
BVT Bouvet Island
BRA Brazil
IOT British Indian Ocean Territory
BRN Brunei Darussalam
BGR Bulgaria
BFA Burkina Faso
BDI Burundi
CPV Cabo Verde
KHM Cambodia
CMR Cameroon
CAN Canada
CYM Cayman Islands
CAF Central African Republic
TCD Chad
CHL Chile
CHN China
CXR Christmas Island
CCK Cocos (Keeling) Islands
COL Colombia
COM Comoros
COG Congo
COD Democratic Republic of the Congo
COK Cook Islands
CRI Costa Rica
CIV Côte d'Ivoire
HRV Croatia
CUB Cuba
CUW Curaçao
CYP Cyprus
CZE Czechia
DNK Denmark
DJI Djibouti
DMA Dominica
DOM Dominican Republic
ECU Ecuador
EGY Egypt
SLV El Salvador
GNQ Equatorial Guinea
ERI Eritrea
EST Estonia
SWZ Eswatini
ETH Ethiopia
FLK Falkland Islands
FRO Faroe Islands
FJI Fiji
FIN Finland
FRA France
GUF French Guiana
PYF French Polynesia
ATF French Southern Territories
GAB Gabon
GMB Gambia
GEO Georgia
DEU Germany
GHA Ghana
GIB Gibraltar
GRC Greece
GRL Greenland
GRD Grenada
GLP Guadeloupe
GUM Guam
GTM Guatemala
GGY Guernsey
GIN Guinea
GNB Guinea-Bissau
GUY Guyana
HTI Haiti
HMD Heard Island and McDonald Islands
VAT Holy See
HND Honduras
HKG Hong Kong
HUN Hungary
ISL Iceland
IND India
IDN Indonesia
IRN Iran
IRQ Iraq
IRL Ireland
IMN Isle of Man
ISR Israel
ITA Italy
JAM Jamaica
JPN Japan
JEY Jersey
JOR Jordan
KAZ Kazakhstan
KEN Kenya
KIR Kiribati
XKX Kosovo
PRK North Korea
KOR South Korea
KWT Kuwait
KGZ Kyrgyzstan
LAO Laos
LVA Latvia
LBN Lebanon
LSO Lesotho
LBR Liberia
LBY Libya
LIE Liechtenstein
LTU Lithuania
LUX Luxembourg
MAC Macao
MDG Madagascar
MWI Malawi
MYS Malaysia
MDV Maldives
MLI Mali
MLT Malta
MHL Marshall Islands
MTQ Martinique
MRT Mauritania
MUS Mauritius
MYT Mayotte
MEX Mexico
FSM Micronesia
MDA Moldova
MCO Monaco
MNG Mongolia
MNE Montenegro
MSR Montserrat
MAR Morocco
MOZ Mozambique
MMR Myanmar
NAM Namibia
NRU Nauru
NPL Nepal
NLD Netherlands
NCL New Caledonia
NZL New Zealand
NIC Nicaragua
NER Niger
NGA Nigeria
NIU Niue
NFK Norfolk Island
MKD North Macedonia
MNP Northern Mariana Islands
NOR Norway
OMN Oman
PAK Pakistan
PLW Palau
PSE Palestine
PAN Panama
PNG Papua New Guinea
PRY Paraguay
PER Peru
PHL Philippines
PCN Pitcairn
POL Poland
PRT Portugal
PRI Puerto Rico
QAT Qatar
REU Réunion
ROU Romania
RUS Russia
RWA Rwanda
BLM Saint Barthélemy
SHN Saint Helena, Ascension and Tristan da Cunha
KNA Saint Kitts and Nevis
LCA Saint Lucia
MAF Saint Martin
SPM Saint Pierre and Miquelon
VCT Saint Vincent and the Grenadines
WSM Samoa
SMR San Marino
STP Sao Tome and Principe
SAU Saudi Arabia
SEN Senegal
SRB Serbia
SYC Seychelles
SLE Sierra Leone
SGP Singapore
SXM Sint Maarten
SVK Slovakia
SVN Slovenia
SLB Solomon Islands
SOM Somalia
ZAF South Africa
SGS South Georgia and the South Sandwich Islands
SSD South Sudan
ESP Spain
LKA Sri Lanka
SDN Sudan
SUR Suriname
SJM Svalbard and Jan Mayen
SWE Sweden
CHE Switzerland
SYR Syria
TWN Taiwan
TJK Tajikistan
TZA Tanzania
THA Thailand
TLS Timor-Leste
TGO Togo
TKL Tokelau
TON Tonga
TTO Trinidad and Tobago
TUN Tunisia
TUR Türkiye
TKM Turkmenistan
TCA Turks and Caicos Islands
TUV Tuvalu
UGA Uganda
UKR Ukraine
ARE United Arab Emirates
GBR United Kingdom
USA United States
UMI United States Minor Outlying Islands
URY Uruguay
UZB Uzbekistan
VUT Vanuatu
VEN Venezuela
VNM Vietnam
VGB British Virgin Islands
VIR U.S. Virgin Islands
WLF Wallis and Futuna
ESH Western Sahara
YEM Yemen
ZMB Zambia
ZWE Zimbabwe
"""

COUNTRY_NAMES: dict[str, str] = dict(line.split(" ", 1) for line in _COUNTRIES.strip().splitlines())

# Codes that appear in passports' machine-readable zones but are not ISO 3166 alpha-3.
_MRZ_CODE_ALIASES = {
    "D": "DEU",  # Germany prints a single letter
    "GBD": "GBR",
    "GBN": "GBR",
    "GBO": "GBR",
    "GBP": "GBR",
    "GBS": "GBR",
    "RKS": "XKX",
}

_EXTRA_COUNTRY_NAMES = {
    "united states of america": "USA",
    "america": "USA",
    "us": "USA",
    "u.s.": "USA",
    "u.s.a.": "USA",
    "uk": "GBR",
    "great britain": "GBR",
    "britain": "GBR",
    "england": "GBR",
    "scotland": "GBR",
    "wales": "GBR",
    "uae": "ARE",
    "u.a.e.": "ARE",
    "emirates": "ARE",
    "the united arab emirates": "ARE",
    "russian federation": "RUS",
    "republic of korea": "KOR",
    "korea": "KOR",
    "iran, islamic republic of": "IRN",
    "islamic republic of iran": "IRN",
    "viet nam": "VNM",
    "syrian arab republic": "SYR",
    "lao people's democratic republic": "LAO",
    "czech republic": "CZE",
    "turkey": "TUR",
    "ivory coast": "CIV",
    "cote d'ivoire": "CIV",
    "cape verde": "CPV",
    "swaziland": "SWZ",
    "macedonia": "MKD",
    "burma": "MMR",
    "state of palestine": "PSE",
    "vatican": "VAT",
    "brunei": "BRN",
    "dr congo": "COD",
    "republic of the congo": "COG",
    "netherlands (the)": "NLD",
    "holland": "NLD",
}

# Nationality adjectives, as printed in the visual zone of many passports.
_DEMONYMS = {
    "afghan": "AFG",
    "algerian": "DZA",
    "american": "USA",
    "argentine": "ARG",
    "australian": "AUS",
    "austrian": "AUT",
    "bahraini": "BHR",
    "bangladeshi": "BGD",
    "belgian": "BEL",
    "brazilian": "BRA",
    "british": "GBR",
    "bulgarian": "BGR",
    "canadian": "CAN",
    "chinese": "CHN",
    "danish": "DNK",
    "dutch": "NLD",
    "egyptian": "EGY",
    "emirati": "ARE",
    "ethiopian": "ETH",
    "filipino": "PHL",
    "filipina": "PHL",
    "finnish": "FIN",
    "french": "FRA",
    "german": "DEU",
    "greek": "GRC",
    "indian": "IND",
    "indonesian": "IDN",
    "iranian": "IRN",
    "iraqi": "IRQ",
    "irish": "IRL",
    "italian": "ITA",
    "japanese": "JPN",
    "jordanian": "JOR",
    "kazakh": "KAZ",
    "kenyan": "KEN",
    "korean": "KOR",
    "kuwaiti": "KWT",
    "lebanese": "LBN",
    "malaysian": "MYS",
    "mexican": "MEX",
    "moroccan": "MAR",
    "nepalese": "NPL",
    "nepali": "NPL",
    "new zealander": "NZL",
    "nigerian": "NGA",
    "norwegian": "NOR",
    "omani": "OMN",
    "pakistani": "PAK",
    "palestinian": "PSE",
    "polish": "POL",
    "portuguese": "PRT",
    "qatari": "QAT",
    "romanian": "ROU",
    "russian": "RUS",
    "saudi": "SAU",
    "saudi arabian": "SAU",
    "singaporean": "SGP",
    "south african": "ZAF",
    "spanish": "ESP",
    "sri lankan": "LKA",
    "sudanese": "SDN",
    "swedish": "SWE",
    "swiss": "CHE",
    "syrian": "SYR",
    "thai": "THA",
    "tunisian": "TUN",
    "turkish": "TUR",
    "ukrainian": "UKR",
    "uzbek": "UZB",
    "vietnamese": "VNM",
    "yemeni": "YEM",
}


def _fold(text: str) -> str:
    """Case- and accent-insensitive comparison key."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().casefold()


_COUNTRY_LOOKUP: dict[str, str] = {
    **{_fold(name): code for code, name in COUNTRY_NAMES.items()},
    **{_fold(name): code for name, code in _EXTRA_COUNTRY_NAMES.items()},
    **{_fold(name): code for name, code in _DEMONYMS.items()},
}


def country_code(raw: str) -> str | None:
    """ISO 3166-1 alpha-3 code for a code, country name or nationality adjective."""
    text = raw.strip()
    if not text:
        return None
    upper = text.upper().replace("<", "")
    if upper in COUNTRY_NAMES:
        return upper
    if upper in _MRZ_CODE_ALIASES:
        return _MRZ_CODE_ALIASES[upper]
    return _COUNTRY_LOOKUP.get(_fold(text))


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "as": "Assamese",
    "az": "Azerbaijani",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "dv": "Dhivehi",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "eu": "Basque",
    "fa": "Persian",
    "ff": "Fula",
    "fi": "Finnish",
    "fr": "French",
    "ga": "Irish",
    "gl": "Galician",
    "gu": "Gujarati",
    "ha": "Hausa",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "ig": "Igbo",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "ku": "Kurdish",
    "ky": "Kyrgyz",
    "lb": "Luxembourgish",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mg": "Malagasy",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "mt": "Maltese",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "ny": "Chichewa",
    "om": "Oromo",
    "or": "Odia",
    "pa": "Punjabi",
    "pl": "Polish",
    "ps": "Pashto",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "rw": "Kinyarwanda",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sn": "Shona",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tajik",
    "th": "Thai",
    "ti": "Tigrinya",
    "tk": "Turkmen",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "wo": "Wolof",
    "xh": "Xhosa",
    "yo": "Yoruba",
    "zh": "Chinese",
    "zu": "Zulu",
}
_LANGUAGE_LOOKUP = {
    **{_fold(name): code for code, name in LANGUAGE_NAMES.items()},
    "filipino": "tl",
    "farsi": "fa",
    "mandarin": "zh",
    "cantonese": "zh",
}


def language_code(raw: str) -> str | None:
    """ISO 639-1 code for a code (optionally with a region, e.g. 'ar-AE') or a name."""
    text = raw.strip()
    base = text.split("-")[0].split("_")[0].lower()
    if base in LANGUAGE_NAMES:
        return base
    return _LANGUAGE_LOOKUP.get(_fold(text))


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


CURRENCIES: frozenset[str] = frozenset(
    {
        "AED", "AUD", "BDT", "BHD", "BRL", "CAD", "CHF", "CNY", "DKK", "EGP", "EUR", "GBP",
        "HKD", "IDR", "INR", "JOD", "JPY", "KES", "KRW", "KWD", "LBP", "LKR", "MXN", "MYR",
        "NGN", "NOK", "NPR", "NZD", "OMR", "PHP", "PKR", "QAR", "RUB", "SAR", "SEK", "SGD",
        "THB", "TRY", "USD", "ZAR",
    }
)  # fmt: skip

CURRENCY_ALIASES: dict[str, str] = {
    "DHS": "AED",
    "DH": "AED",
    "DIRHAM": "AED",
    "DIRHAMS": "AED",
    "د.إ": "AED",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "US$": "USD",
}


def fold(text: str) -> str:
    return _fold(text)
