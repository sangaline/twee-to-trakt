#!/usr/bin/env python3
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import trakt.core
from tinydb import Query, TinyDB
from trakt import init
from trakt.tv import TVShow

# Setup logger
logging.basicConfig(
    format="%(asctime)s [%(levelname)7s] :: %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Adjust this value to increase/decrease your requests between episodes.
# Make to remain within the rate limit: https://trakt.docs.apiary.io/#introduction/rate-limiting
DELAY_BETWEEN_EPISODES_IN_SECONDS = 1

# Create a database to keep track of completed processes
database = TinyDB("localStorage.json")
syncedEpisodesTable = database.table("SyncedEpisodes")
userMatchedShowsTable = database.table("TweeTraktUserMatched")


class Expando(object):
    pass


def isAuthenticated():
    if not os.path.exists("pytrakt.json"):
        return False
    with open("pytrakt.json") as f:
        data = json.load(f)
        daysBeforeExpiration = (
            datetime.fromtimestamp(data["OAUTH_EXPIRES_AT"]) - datetime.now()
        ).days
        if daysBeforeExpiration < 1:
            return False
        return True


def getConfiguration():
    configEx = Expando()

    with open("config.json") as f:
        data = json.load(f)

    configEx.TRAKT_USERNAME = data["TRAKT_USERNAME"]
    configEx.CLIENT_ID = data["CLIENT_ID"]
    configEx.CLIENT_SECRET = data["CLIENT_SECRET"]
    configEx.GDPR_WORKSPACE_PATH = data.get("GDPR_WORKSPACE_PATH", ".")

    CONFIG_SINGLETON = configEx

    return CONFIG_SINGLETON


config = getConfiguration()


def initTraktAuth():
    if isAuthenticated():
        return True
    # Set the method of authentication
    trakt.core.AUTH_METHOD = trakt.core.OAUTH_AUTH
    trakt.core.CONFIG_PATH = "pytrakt.json"
    return init(
        config.TRAKT_USERNAME,
        store=True,
        client_id=config.CLIENT_ID,
        client_secret=config.CLIENT_SECRET,
    )


# With a given title, check if it contains a year (e.g Doctor Who (2005))
# and then return this value, with the title and year removed to improve
# the accuracy of Trakt results.


def getYearFromTitle(title):
    ex = Expando()

    try:
        # Use a regex expression to get the value within the brackets e.g The Americans (2017)
        yearSearch = re.search(r"\(([A-Za-z0-9_]+)\)", title)
        yearValue = yearSearch.group(1)
        # Then, get the title without the year value included
        titleValue = title.split("(")[0].strip()
        # Put this together into an object
        ex.titleWithoutYear = titleValue
        ex.yearValue = int(yearValue)
        return ex
    except Exception:
        # If the above failed, then the title doesn't include a year
        # so return the object as is.
        ex.titleWithoutYear = title
        ex.yearValue = -1
        return ex


# Shows in Twee are often different to Trakt.TV - in order to improve results and automation,
# calculate how many words are in the title, and return true if more than 50% of the title is a match,
# It seems to improve automation, and reduce manual selection....


def checkTitleNameMatch(tweeTitle, traktTitle):
    # If the name is a complete match, then don't bother comparing them!
    if tweeTitle == traktTitle:
        return True

    # Split the Twee title
    tweeTitleSplit = tweeTitle.split()

    # Create an array of words which are found in the Trakt title
    wordsMatched = []

    # Go through each word of the Twee title, and check if it's in the Trakt title
    for word in tweeTitleSplit:
        if word in traktTitle:
            wordsMatched.append(word)

    # Then calculate what percentage of words matched
    quotient = len(wordsMatched) / len(traktTitle.split())
    percentage = quotient * 100

    # If more than 50% of words in the Twee title exist in the Trakt title,
    # then return the title as a possibility to use
    return percentage > 50


# Using Twee data (Name of Show, Season No and Episode) - find the corresponding show
# in Trakt.TV either by automation, or asking the user to confirm.


def getShowByName(name, seasonNo, episodeNo, tvShowYear):
    # Parse the TV Show's name for year, if one is present in the string
    titleObj = getYearFromTitle(name)

    # Create a boolean to indicate if the title contains a year,
    # this is used later on to improve the accuracy of picking
    # from search results
    doesTitleIncludeYear = titleObj.yearValue != -1

    # If the title contains a year, then replace the local variable with the stripped version
    if doesTitleIncludeYear:
        name = titleObj.titleWithoutYear
    year = titleObj.yearValue if doesTitleIncludeYear else tvShowYear

    # Request the Trakt API for search results, using the name
    tvSearch = TVShow.search(name)

    # Create an array of shows which have been matched
    showsWithSameName = []

    # Go through each result from the search
    for show in tvSearch:
        # Check if the title is a match, based on our conditions (e.g over 50% of words match)
        if checkTitleNameMatch(name, show.title):
            # If the title included the year of broadcast, then we can be more picky in the results
            # to look for a show with a broadcast year that matches
            if doesTitleIncludeYear or (year and year > -1):
                # If the show title is a 1:1 match, with the same broadcast year, then bingo!
                if (name == show.title) and (show.year == year):
                    # Clear previous results, and only use this one
                    showsWithSameName = []
                    showsWithSameName.append(show)
                    break

                # Otherwise, only add the show if the broadcast year matches
                if show.year == year:
                    showsWithSameName.append(show)
            # If the program doesn't have the broadcast year, then add all the results
            else:
                showsWithSameName.append(show)

    # Sweep through the results once more for 1:1 title name matches,
    # then if the list contains one entry with a 1:1 match, then clear the array
    # and only use this one!
    completeMatchNames = []
    for nameFromSearch in showsWithSameName:
        if nameFromSearch.title == name:
            completeMatchNames.append(nameFromSearch)

    if len(completeMatchNames) == 1:
        showsWithSameName = completeMatchNames

    # If the search contains multiple results, then we need to confirm with the user which show
    # the script should use, or access the local database to see if the user has already provided
    # a manual selection
    if len(showsWithSameName) > 1:

        # Query the local database for existing selection
        userMatchedQuery = Query()
        queryResult = userMatchedShowsTable.search(userMatchedQuery.ShowName == name)

        # If the local database already contains an entry for a manual selection
        # then don't bother prompting the user to select it again!
        if len(queryResult) == 1:
            # Get the first result from the query
            firstMatch = queryResult[0]
            # Get the value contains the selection index
            firstMatchSelectedIndex = int(firstMatch.get("UserSelectedIndex"))
            # Check if the user previously requested to skip the show
            skipShow = firstMatch.get("SkipShow")
            # If the user did not skip, but provided an index selection, get the
            # matching show
            if not skipShow:
                return showsWithSameName[firstMatchSelectedIndex]
            # Otherwise, return None, which will trigger the script to skip
            # and move onto the next show
            else:
                return None
        # If the user has not provided a manual selection already in the process
        # then prompt the user to make a selection
        else:
            print(
                f"INFO - MANUAL INPUT REQUIRED: The Twee data for Show '{name}' (Season {seasonNo}, Episode {episodeNo}) has {len(showsWithSameName)} matching Trakt shows with the same name."
            )

            # Output each show for manual selection
            for idx, item in enumerate(showsWithSameName):
                # Display the show's title, broadcast year, amount of seasons and a link to the Trakt page.
                # This will provide the user with enough information to make a selection.
                print(
                    f"    ({idx + 1}) {item.title} - {item.year} - {len(item.seasons)} Season(s) - More Info: https://trakt.tv/{item.ext}"
                )

            while True:
                try:
                    # Get the user's selection, either a numerical input, or a string 'SKIP' value
                    indexSelected = input(
                        "Please make a selection from above (or enter SKIP):"
                    )

                    if indexSelected != "SKIP":
                        # Since the value isn't 'skip', check that the result is numerical
                        indexSelected = int(indexSelected) - 1
                        # Exit the selection loop
                        break
                    # Otherwise, exit the loop
                    else:
                        break
                # Still allow the user to provide the exit input, and kill the program
                except KeyboardInterrupt:
                    sys.exit("Cancel requested...")
                # Otherwise, the user has entered an invalid value, warn the user to try again
                except Exception:
                    logging.error(
                        f"Sorry! Please select a value between 0 to {len(showsWithSameName)}"
                    )

            # If the user entered 'SKIP', then exit from the loop with no selection, which
            # will trigger the program to move onto the next episode
            if indexSelected == "SKIP":
                # Record that the user has skipped the TV Show for import, so that
                # manual input isn't required everytime
                userMatchedShowsTable.insert(
                    {"ShowName": name, "UserSelectedIndex": 0, "SkipShow": True}
                )

                return None
            # Otherwise, return the selection which the user made from the list
            else:
                selectedShow = showsWithSameName[int(indexSelected)]

                userMatchedShowsTable.insert(
                    {
                        "ShowName": name,
                        "UserSelectedIndex": indexSelected,
                        "SkipShow": False,
                    }
                )

                return selectedShow

    else:
        if len(showsWithSameName) > 0:
            # If the search returned only one result, then awesome!
            # Return the show, so the import automation can continue.
            return showsWithSameName[0]
        else:
            return None


def load_rows(backup_filename: str):
    with open(backup_filename) as f:
        data = json.load(f)
    rows = []
    seen_ids = set()
    for profile in data:
        for show in profile["Shows"]:
            for episode in show["Episodes"]:
                # Skip unwatched episodes
                if episode["Watched"] != "1":
                    continue

                # The episode IDs aren't unique for some reason, so we construct a synthetic one.
                episode_id = (
                    episode["Season"]
                    + "-"
                    + episode["Episode"]
                    + "-"
                    + show["SeriesId"]
                    + "-"
                    + episode["EpisodeId"]
                )
                if episode_id in seen_ids:
                    raise ValueError(
                        f'The episode ID "{episode_id}" exists for more than one episode.'
                    )

                seen_ids.add(episode_id)
                rows.append(
                    {
                        "tv_show_name": show["Name"],
                        "tv_show_year": int(show["FirstAired"].split("-")[0])
                        if show["FirstAired"]
                        else -1,
                        "episode_id": episode_id,
                        "episode_season_number": int(episode["Season"]),
                        "episode_number": int(episode["Episode"]),
                        "episode_aired": datetime.fromisoformat(episode["Aired"])
                        if episode["Aired"]
                        else None,
                    }
                )

    return rows


def processWatchedShows(backup_filename: str, dry_run: bool):
    # Total number of API errors in a row
    errorStreak = 0
    # Loop through each episode
    rows = load_rows(backup_filename)
    rowsTotal = len(rows)
    for rowsCount, row in enumerate(rows):
        # Get the name of the TV show
        tvShowName = row["tv_show_name"]
        # Get the year the TV show aired
        tvShowYear = row["tv_show_year"]
        # Get the Twee Episode Id
        tvShowEpisodeId = row["episode_id"]
        # Get the Twee Season Number
        tvShowSeasonNo = row["episode_season_number"]
        # Get the Twee Episode Number
        tvShowEpisodeNo = row["episode_number"]
        # Get the timestamp that the episode aired
        tvShowEpisodeAired = row["episode_aired"]

        # Query the local database for previous entries indicating that
        # the episode has already been imported in the past. Which will
        # ease pressure on Twee's API server during a retry of the import
        # process, and just save time overall without needing to create network requests
        episodeCompletedQuery = Query()
        queryResult = syncedEpisodesTable.search(
            episodeCompletedQuery.episodeId == tvShowEpisodeId
        )

        # If the query returned no results, then continue to import it into Trakt
        if len(queryResult) == 0:
            # Create a repeating loop, which will break on success, but repeats on failures
            while True:
                # If more than 10 errors occurred in one streak, whilst trying to import the episode
                # then give up, and move onto the next episode, but warn the user.
                if errorStreak > 10:
                    logging.warning(
                        "An error occurred 10 times in a row... skipping episode..."
                    )
                    break
                try:
                    # Sleep for a second between each process, before going onto the next watched episode.
                    # This is required to remain within the API rate limit, and use the API server fairly.
                    # Other developers share the service, for free - so be considerate of your usage.
                    time.sleep(DELAY_BETWEEN_EPISODES_IN_SECONDS)
                    # Search Trakt for the TV show matching Twee's title value
                    traktShowObj = getShowByName(
                        tvShowName, tvShowSeasonNo, tvShowEpisodeNo, tvShowYear
                    )
                    # If the method returned 'None', then this is an indication to skip the episode, and
                    # move onto the next one
                    if traktShowObj is None:
                        logging.warning(f"No match was found for '{tvShowName}'!")
                        break
                    # Show the progress of the import on-screen
                    logging.info(
                        f"({rowsCount+1}/{rowsTotal}) - Processing '{tvShowName}' Season {tvShowSeasonNo} / Episode {tvShowEpisodeNo}"
                        f" matched as {traktShowObj.title} ({traktShowObj.year})."
                    )
                    # Get the season from the Trakt API
                    season = next(
                        season
                        for season in traktShowObj.seasons
                        if season.number == tvShowSeasonNo
                    )
                    # Get the episode from the season
                    episode = next(
                        episode
                        for episode in season.episodes
                        if episode.number == tvShowEpisodeNo
                    )

                    # If this is a dry-run, then bail before updating anything in Trakt.
                    if dry_run:
                        break

                    # Mark the episode as watched!
                    # We pretend that we watched it when it aired because the default behavior on
                    # Trakt would be to set the watch time to when we run the import backfill.
                    # Twee unfortunately doesn't store when the show was actually watched.
                    episode.mark_as_seen(watched_at=tvShowEpisodeAired)
                    # Add the episode to the local database as imported, so it can be skipped,
                    # if the process is repeated
                    syncedEpisodesTable.insert({"episodeId": tvShowEpisodeId})
                    # Clear the error streak on completing the method without errors
                    errorStreak = 0
                    break
                # Catch errors which occur because of an incorrect array index. This occurs when
                # an incorrect Trakt show has been selected, with season/episodes which don't match Twee.
                # It can also occur due to a bug in Trakt Py, whereby some seasons contain an empty array of episodes.
                except (IndexError, StopIteration):
                    tvShowSlug = traktShowObj.to_json()["shows"][0]["ids"]["ids"][
                        "slug"
                    ]
                    logging.warning(
                        f"({rowsCount}/{rowsTotal}) - {tvShowName} Season {tvShowSeasonNo}, Episode {tvShowEpisodeNo} does not exist in Trakt! (https://trakt.tv/shows/{tvShowSlug}/seasons/{tvShowSeasonNo}/episodes/{tvShowEpisodeNo})"
                    )
                    break
                # Catch any errors which are raised because a show could not be found in Trakt
                except trakt.errors.NotFoundException:
                    logging.warning(
                        f"({rowsCount}/{rowsTotal}) - {tvShowName} Season {tvShowSeasonNo}, Episode {tvShowEpisodeNo} does not exist (search) in Trakt!"
                    )
                    break
                # Catch errors because of the program breaching the Trakt API rate limit
                except trakt.errors.RateLimitException:
                    logging.warning(
                        "The program is running too quickly and has hit Trakt's API rate limit! Please increase the delay between "
                        + "episdoes via the variable 'DELAY_BETWEEN_EPISODES_IN_SECONDS'. The program will now wait 60 seconds before "
                        + "trying again."
                    )
                    time.sleep(60)

                    # Mark the exception in the error streak
                    errorStreak += 1
                # Catch a JSON decode error - this can be raised when the API server is down and produces a HTML page, instead of JSON
                except json.decoder.JSONDecodeError:
                    logging.warning(
                        f"({rowsCount}/{rowsTotal}) - A JSON decode error occuring whilst processing {tvShowName} "
                        + f"Season {tvShowSeasonNo}, Episode {tvShowEpisodeNo}! This might occur when the server is down and has produced "
                        + "a HTML document instead of JSON. The script will wait 60 seconds before trying again."
                    )

                    # Wait 60 seconds
                    time.sleep(60)

                    # Mark the exception in the error streak
                    errorStreak += 1
                # Catch a CTRL + C keyboard input, and exits the program
                except KeyboardInterrupt:
                    sys.exit("Cancel requested...")
        # Skip the episode
        else:
            logging.info(
                f"({rowsCount}/{rowsTotal}) - Already imported, skipping '{tvShowName}' Season {tvShowSeasonNo} / Episode {tvShowEpisodeNo}."
            )


def start(backup_filename: str):
    # Create the initial authentication with Trakt, before starting the process.
    if initTraktAuth():
        # Display a menu selection
        print(">> What do you want to do?")
        print("    1) Import Watch History from Twee")
        print("    2) Dry-run of matching Twee shows against Trakt")

        while True:
            try:
                menuSelection = input("Enter your menu selection [1]: ")
                menuSelection = 1 if not menuSelection else int(menuSelection)
                break
            except ValueError:
                logging.warning("Invalid input. Please enter a numerical number.")
        # Start the process which is required
        if menuSelection == 1:
            # Invoke the method which will import episodes which have been watched
            # from Twee into Trakt.
            processWatchedShows(backup_filename, dry_run=False)
        elif menuSelection == 2:
            # Invoke the method which will import episodes which have been watched
            # from Twee into Trakt.
            processWatchedShows(backup_filename, dry_run=True)
        else:
            logging.warning("Sorry - that's an unknown menu selection")
    else:
        logging.error(
            "ERROR: Unable to complete authentication to Trakt - please try again."
        )


if __name__ == "__main__":
    backup_filename = sys.argv[1] if len(sys.argv) > 1 else "twee.json"
    if not os.path.exists(backup_filename):
        logging.error(f'The backup file "{backup_filename}" does not exist.')
        sys.exit(1)

    # Check that the user has created the config file
    if os.path.exists("config.json"):
        start(backup_filename)
    else:
        logging.error(
            "The 'config.json' file cannot be found - have you created it yet?"
        )
