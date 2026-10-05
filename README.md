# Mandate

This repository holds all the code used to write and update listings to the Mandate jobs database. 

## Packages used

Using Python scraping packages, each website requires a customized workflow depending on whether there is an API, the consistency of the HTML structure from page to page, etc. 

For sites with APIs, the requests package is used. For sites without APIs, urllib and bs4 are used to pull data from the HTML structure. The latter requires more manual review and is more susceptible to mistakes.

Disclaimer: I have also used AI (Claude free plan) in a limited capacity in the creation of some of the more complex parsing of locations and categorizations, driven by manual review by myself, for example with regex patterns, which I then review before implementing and using on the data. No AI is used to parse the data automatically beyond when the code is written, to ensure I have full control over the rules used to categorize listings.  

## Data storage

Data is upserted into a MongoDB table (see combiner.py), where data is stored in a consistent format with unique ID identifiers. Before upserting, data is also parsed for categorization

## Categorization

Using, if available, staff categories and grade levels, and falling back on string parsing, one categorization available is career stage. If you have any issues with the way we've done this (see experience.py), please raise a ticket and I'm open to adjusting the thinking behind it.

Using the job description, we also attempt with each listing to determine what minimum education level is required (ex. does it require a completed advanced university degree). 

The data on this site is solely for personal use and to bridge the gap between so many different sites. Please contact me with any issues about data usage. 
