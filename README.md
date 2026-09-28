# Museum of Play Collections API

The Museum of Play is a conceptual (fictitious) museum dedicated to critical ludology, based in Seattle, WA.

## Decoding IDs

Artists and exhibitions are all encoded into our collections API with unique semantic IDs.

Artist IDs start with the prefix _ART-_, then the first letter of the artist's given name, the first two letters of the artist's surname, and finally a unique four-digit number.

Exhibition IDs start with the prefix _EXH-_, and then a unique four-digit number.

## Accession Numbers

Artworks are identified by their accession number. Accession numbers start with the year an artwork was acquired, then a period, then a unique four-digit number.

# Acknowledgements

The Museum of Play Collections API is based on the OpenAPI specification and built on top of Redocly's [open-api](https://github.com/Redocly/cafe-api) repository.