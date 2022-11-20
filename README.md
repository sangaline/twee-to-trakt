# Twee to Trakt - Import Script

A Python script to import Twee tracked episode data into Trakt.TV - using data export provided by Twee in the app for backups.
This is a hastily modified version of [TvTimeToTrakt](https://github.com/lukearran/TvTimeToTrakt/) to import data from the Twee Android app instead of TvTime.
@lukearran is the original author.

# Notes

1. The script is using limited data provided from the Twee backup - so the accuracy isn't 100%. But you will be prompted to manually pick the Trakt show, when it can't be determined automatically.
2. Twee doesn't store when each episode is watched. The time that the episode originally aired will be used as the watch time when adding data to Trakt.
3. A delay of 1 second is added between each episode to ensure fair use of Trakt's API server. You can adjust this for your own import, but make sure it's at least 0.75 second to remain within the rate limit: https://trakt.docs.apiary.io/#introduction/rate-limiting
4. Episodes which have been processed will be saved to a TinyDB file `localStorage.json` - when you restart the script, the program will skip those episodes which have been marked 'imported'.

# Setup

## Get your Data

1. Open the Twee Android app.
2. Navigate to Settings, and then "Backup and restore" under Settings.
3. Click "Backup" and select "Local" as a backup mechanism.
4. A toast message will appear telling you where the backup was saved on your phone. Find this file in the file manager, email it to yourself as an attachment, place it in the project directory, and rename it to `twee.json`.

## Register API Access at Trakt

1. Go to "Settings" under your profile
2. Select ["Your API Applications"](https://trakt.tv/oauth/applications)
3. Select "New Application"
4. Provide a name into "Name" e.g John Smith Import from Twee
5. Paste "urn:ietf:wg:oauth:2.0:oob" into "Redirect uri:"
6. Click "Save App"
7. Make note of your details to be used later.

## Setup Script

### Install Required Libraries

Install the following frameworks via Pip:

```
python -m pip install -r requirements.txt
```

### Setup Configuration

Create a new file named `config.json` in the same directory of `twee_to_trakt.py`, using the below JSON contents (replace the values with your own).

```
{
    "CLIENT_ID": "YOUR_CLIENT_ID",
    "CLIENT_SECRET": "YOUR_CLIENT_SECRET",
    "TRAKT_USERNAME": "YOUR_TRAKT_USERNAME"
}
```

Once the config is in place, execute the program using `python twee_to_trakt.py`. The process isn't 100% automated - you will need to pop back, especially with large imports, to check if the script requires a manual user input.

##### Credit

This is a hastily modified version of [TvTimeToTrakt](https://github.com/lukearran/TvTimeToTrakt/) to import data from the Twee Android app instead of TvTime.
@lukearran is the original author.
