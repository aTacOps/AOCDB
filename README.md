# AOCDB
Simple Tkinker GUI-based player tracker for Ashes of Creation

This started as a way for me to keep track of the players I encountered while testing Ashes of Creation.

Overtime it has evolved a little bit.  Keeping in mind that the future state of this game involves a lot of politics between players, guilds, and nodes I decided to expand on it a bit.

I plan to add more features and refine it a bit, as I am fairly new to this whole coding thing.

For now it has a basic GUI built through Tkinker.
It keeps all of the player information in a Firebase Store.
There is a built in authentication method, that could also leverage the security rules of Firebase.

I also added export to markdown so that I could view all of the information in a visual style on Obsidian.  All of the information is sent to the DB as well as to Obsidian with links to other markdown files if applicable.

I have removed the FirebaseService information so I don't get a ton of random additions to the database in the event someone finds a way around the auth.  Be sure to fill in your own information here if you'd like to live test it.  The export to markdown function should also be explored as right now that function only goes to a local folder for Obsidian.

As of right now there are a lot of built in debug functions just to provide data in the event something isn't playing nice.
