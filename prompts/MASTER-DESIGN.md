# Winerank Application 

## Overview

Let's build new application Winerank. The purpose of Winerank ultimately is to offer users unique view into wines based on how fine restaurants around the world feature them on their wine lists. We want to focus on the wine restaurants only because their wine lists are both usually large and feature select wines in a variety of price.

Underneath the system we will create and maintain a wine database based on the restaurant wine lists collected and parsed online from the restaurants worldwide. The general approach to wine ranking should be the more the wine occurs in different restaurant lists the higher rank it attains. It can also consider the restaurant quality and the quality of its wine list.

The wines are the wine bottles the restaurants list for sale in their wine lists. They are defined at the level of the winery and concrete label including vintage and other attributes generally associated with a bottle of wine.

The goal is to find, collect, parse and analyze as many wine lists from the reputable restaurants as possible to collect enough statistics to rank wines based on their presence on the lists. 

## User Questions

The web application should be able to answer questions like these:
- What is the ranking of the wine X?
- Which Pinot Noir has the best ranking?
- Is the wine X a popular wine?
- Is wine X a better choice than wine Y?
- What is the most expensive vintage of wine X?
- Which Pinot Noir from Russian River Valley is most sought after?
- What Sauvignon Blanc is most popular in New York city?
- Give me the best choice of white wine for the restaurant A under $100 
- What are is best Malbec overall in restaurant A?
- What is the most popular wine in the world?
- What is the most expensive wine in France?
- What Spanish wine I should order in restaurant A under $50?
- List me top 10 wines in New York city
- What are most expensive wines in the world?

These examples are in no way complete, and the system should be able to answer rich set of questions about wines in general basing its answers on the wine database it maintains.

## High Level Functionality

We are building a brand-new wine ranking application that will score wines from all around the world based on their presence on the restaurant’s wine lists publicly available online. The application is called Winerank and it will include several collaborating components defined by their function:
- crawl and find restaurants wine lists: includes starting points where to find restaurant lists and their web sites, proceed to the web sites and find restaurant wine lists and download them.
- parse and organize wines: parsing downloaded wine lists found on internet to organize them into internal wine database
- rank wines: wine ranking that ranks wines in the database based on their presence in wine lists, restaurant level, and wine list quality.
- interact with users: let users search, look up, analyze wines and ask free text questions about the wines, based on the ranking and presence in the wine lists.

## Application Components

We will have the following high-level components to start:
1. Restaurant Crawler (or simply Crawler): online crawler and scraper that looks for the restaurants based on certain criteria (we want to start only with certain high-profile restaurants world-wide), then it looks up restaurant web sites to find their wine lists.
2. Wine List Parser (or simply Parser): sophisticated wine parser that takes restaurant wine lists and parses the wine information from them: this might be very challenging and heavy on AI and LLM component because while wine lists contain information about wines their formatting varies widely. That means that the wine parser should be flexible to parse wines from variety of wine lists (we will have examples of wine lists inside data/examples)
3. Winerank Database with DB Manager: the database that stores all information about restaurants, jobs (crawler runs), wine lists, and ultimately the wines with their rankings. Internal manager app that manages Winerank database. It's not clear to me if this should be a separate component or it could be a part of Winerank App - I believe now that this is a separate component as it needs very different way of access to the wine database. This likely evolves into internal Winerank manager application.
4. Wine Ranker (or simply Ranker): algorithmic process that evaluates and assigns a rank to each wine present in the database based on its frequency in the wine lists. This process is defined as a stand-alone component because ranking process is very important and highly customizable process that may run and re-run multiple times based on the updates to data and to algorithm.
5. Web App: user facing web application that tracks, displays, searches wines in the internal data store (database) to display and search wines based on their internally computed score, appearance in the restaurants lists, and other information we collect. This is the consumer web app that demonstrates and give access to all useful features of wine ranking database we build using the rest of components in our project.

## Component Flow

1. Restaurant Crawler finds restaurants and their respective wine lists and downloads them (usually as pdf files, sometimes as HTMLs), but ultimately all probably should be converted to a text that retains internal pdf or html structure (for subsequent parsing the structure will be important).
2. Wine List Parser parses and extracts wines from the downloaded lists to persist them into Wine Database.
3. Wine Ranker processes parsed wines in the database and enriches them with the rankings.

Both web applications use and maintain Winerank database:
1. Winerank Database Manager manages it
2. Winerank Web App lets users access and search Wine Database.

We will build one component at the time in natural order of how we ingest, process, and utilize data from the wine lists.
The following sections discuss each component in details including features, functionality, and implementation.

## Components

### Winerank Database with DB Manager

#### Data Model

The data model is ultimately the core data piece around which all other processes are structured, organized, and executed. The data model must include all information from the wine lists about wines, information about jobs that ingest wine lists, and anything else that is relevant to the application components and that can be parsed, extracted, and represented in the structured format or semi-structured format if parsing is limited.

The database based on the data model is shared between all components.

The following list of entities and their attributes should serve as a foundation for the database we build.

#### Entities

The entities the data model has:
- Restaurant
- Wine List
- Wine
- Job: crawler runs

#### Relationships

Relationships between entities:
- Restaurant may have 0 or more Wine Lists
- Wine may belong to 1 or more Wine Lists
- Wine List is parsed during Batch Job

#### Restaurant
The following attributes are commonly associated with a Restaurant entity: 
- restaurant_name
- restaurant_webpage_url
- wikipedia_url
- reference_url
- last_downloaded
- last_updated
- comment

#### Wine List
The following attributres are commonly associated with a Wine List entity:
- restaurant_name
- list_name
- wine_list_url
- local_file_path
- last_downloaded
- last_updated
- wine_count
- comment 

#### Wine
The following attributes are commonly associated with Wine entity:
- restaurant_name: Restaurant the wine list that contains the wine is from
- name: usually unique wine name, may or may not include or may or may not be the name as the name of the winery
- winery: the winery name that produced the wine
- varietal: wine grape varietal or blend designation or similar, e.g. Riesling, Chenin Blanc, Champagne, Chardonnay, and so on (optional in some cases but usually present or found from the context)
- type: Red, White, Orange, Sparkling, and so on (optional but usually found from the context)
- country: wine country of origin
- region: wine region such as Mosel, Burgundy, Chablis, Sonoma, Napa, and so on (usually different from country but maybe the same)
- vineyard: designated vineyard where the wine grapes sourced from (optional)
- vintage: year of the wine (possible value is non-vintage - NV)
- format: bottle type or by the glass
- price: wine price
- note: any extra info that doesn't fit into the above attributes (optional)

#### Job
Job attributes:
- job_id
- job_date
- job_duration
_ job_status: completed, started, interrupted, resumed, and so on
- additional attributes that make sense

#### SiteOfRecord 
Websites of the record used by the Crawler to start their search for the restaurant wine lists (currently it's Michelin United States site, but more are possible):
- site_name
- site_url
- created_date
- last_time_visited_date
- navigational_notes: text that describes how to navigate this site to list and reach restaurant websites
- additional attributes that make sense

#### Other
If there are any other entities or relationships that belong to data model, we should consider them.

#### Database
Use database that is easy to develop with, deploy on the cloud on VM or as PaaS or SaaS, maintain, Python native or well supported by Python, and finally that supports appropriate use cases. 

#### Database Manager (DB Manager)
Develop online app that lets me and the rest of the development and admin team to work with the database:
- view data
- query data
- update data
- delete data 
- reports, like list of restaurants with downloaded wine lists or finished jobs with status

The app will evolve - for now provide basic functionality to be able to work with the database data.
Use basic technology that would be easy to understand and read by novice UI developer, but good enough to create visually pleasant and usable UI interface and functionality.
We will be deploying those online - so prpose a solution to deploy the app online for scalable consumption - it could be a VM on AWS or something more auotamated. 

Aslo, the DB Manager app doesn't have to be deployed in the cloud but it shoud be able to work with both databases deployed locally or in the cloud.

### Restaurant Crawler Component (Crawler)

This component is an intelligent internet websites crawler with the purpose of navigating restaurant websites to locate, download, and save as rich text the restaurant wine lists.

We have a wine database that contains the list of restaurants. In there we will accumulate information about restaurant websites and restaurant lists, but initially it will be empty. During subsequent Crawler runs it will use it to go directly to the restaurants, but it always should start with a website of record to find all restaurants of the interest. 

The database will include a table for the website of records as well.

#### Navigation

The first approach is to go off the Michelin website as a website of record for the restaurants. Michelin website contains pages devoted to the Michelin restaurants.  Start with [Michelin website for United States](https://guide.michelin.com/us/en/selection/united-states/restaurants) that currently displays 1759 restaurants across 37 pages (on my browser, at the time of this writing). 

We may have other starting points that will require some change in strategy for the Crawler, but for now let's focus on the Michelin site only.

By navigating each page with the list of restaurants in the Michelin site the Crawler should be able to find and parse all restaurants on each page. For each restaurant it should go to the restaurant's page in Michelin website and find the link "Visit Website" (as it stands today) to the restaurant web site. Next, it navigates to a restaurant website via that link "Visit Website". In the restaurant website the Crawler should search for the path to the wine list location or determine that the list is not available (after finite number of attempts or exhausting the website pages). 

We should focus on Michelin-starred restaurants first - Crawler should have a parameter "michelin" (in .env file) that identifies the level of the restaurants to target, e.g. "michelin=3" will crawl restaurants with 3 stars, and "michelin=gourmand" will crawl restaurants with Big Gourmand distinction. The Michelin web site contains filter "Distinction" that limits the list of the restaurants based on the filter.

Note that not every restaurant will have a web site. Such restaurants should still be recorded in wine database with corresponding status that no web site and no wine list found. Keep in mind that they may create a web site in the future, so crawler should try them every time it runs.
Crawler should be smart and use wine database to go directly to the wine list if it already been found before, check if it's new and download new list only. It's very important not to waste resources on parsing the same wine lists multiple times.

Ideally the Crawler will navigate Michelin Guide pages to reach a page for each restaurant and then navigate to the Michelin restaurant website. Then it will search and crawl restaurant's website to find a wine list (keep in mind that not all restaurants post wine lists or make them easily available). To navigate restaurant web site Crawler should implement flexible and powerful logic to navigate, traverse restaurant websites, and find links leading to the wine list as pdf or html. I believe that using programming logic should suffice. Only if LLM use makes implementation more efficient and elegant and powerful then consider it - I want to use LLM in this case only if it simplifies the implementation. 

Here is an actual example of the steps to navigate and to download wine list from the restaurant website ["The Inn at Little Washington"](https://www.theinnatlittlewashington.com/) (after finding it on the Michelin website):
1. go to https://www.theinnatlittlewashington.com/
2. find the menu and choose "Dine" link to navigate to the Dine page
3. in the Dine page find the link "Our Wine Program" and navigate that page 
4. in the Wine Program page find the link "Our Wine List" which references pdf with the wine list
5. download pdf with the restaurant's wine list 
6. record the results in the wine database
   
Consider a solution with an agent enabled with Playwright (or similar browser capabilities) to navigate restaurant web site and make navigational decisions enabled by LLM of choice tasked to search for a restaurant wine list. Have hard limit on the number of links / redirects when searching for a wine list to avoid infinite tasks. Also, stop after searching through all pages within the restaurant website without finding the list. 

Let's have a limit on depth of the links when navigating the restaurant website (not including Michelin site) at 4 (make it a parameter "restaurant_website_depth" in .env file)

The following high level flow of traversing and navigating Michelin web site may work for Crawler:

1. Collect a list of pages with Michelin restaurants from the Michelin website. 
0.1. Filter this list based on the "michelin" parameter.
1. For each Michelin page with the list of the restaurants do the sequence below:
1.1. Find the page for each restaurant on Michelin website
1.2. Find the link to the restaurant website
1.3. Navigate to the restaurant website
1.4. Crawl restuarant website for the link to its wine list
1.5. Download the wine list or terminate without it after finite number of page hits (e.g. 20)
1.6. Continue to next Michelin restaurant from the Michelin page

#### Additional Features

The Crawler should:
- record both successful and unsuccesful outcome for each restaurant
- save the location of the wine list to curcumvent navigational steps next time Crawler processes the same restaurant. That doesn't mean we simply go to the saved list of restaurants - the Crawler always should start with the website of record - in this case Michelin website - to iterate over all new and updated restaurants.
- record all metadata info about wine list so next time we navigate to the same restaurant we know if the wine list is new or the same
- be able stop and resume this process at any time for any reason from the point where we left off. 

We might want to consider maintaining additional Job info in the database that allows us to checkpoint/resume/restart/continue any Crawler job run.
This process should be robust and reliable to interrupt and resume with no overhead or duplciate work. It's up to the agent how to organize the work: collect all restaurant websites first or not. Preferrable the approach should be such that we can parallelize the work.

Automatic scraping should support dynamic web sites for both Michelin site and restaurant sites. That means that it shoud be able to navigate , parse and analyze JavaScript-rendered web pages (React, Vue, Angular, Nuxt.js) by utilizing advanced features of Playwright, for example.

Include a feature that allows manual override of the wine list location per restaurant on case by case basis: probably by using the Wine Database with information about restaurant and location of its wine list. If the database already contains restaurant and its wine list info then just follow this link, the worst case report that the link is not valid anymore. This approach should work for both the manual override and for the restaurant sites that were crawled before and now just need an update of their wine list.

Despite the above features keep the logic and implementation simple, concise and readable. If need to choose between simplicty and functionality always side the simpler solution - functionality can be added later.

#### Downloaded Wine List

The Crawler agent also include transforming (exporting) of the wine lists from pdf or html to a rich format text files that preserve and retain all structural and logical content of the wine lists. Python package "pdfplumber" appears as a tool of choice for this task but do your own analysis first.

The resulting rich text file will be input for the Wine List Parser agent component.

#### Operations

The result of the Crawler run should be updated Wine Database with the restaurants and locations of their downloaded and parsed wine lists.

The Crawler should support running multiple jobs in parallel, for example one for "michelin=3" restaurants and another for "michelin=2" restaurants.

#### Error Handling
Crawler should be able to resume its run if the run was interrupted due to crash or other reasons. The Crawler should resume exactly where it left off by recording (checkpointing) its progress accordingly, probably using the Wine Database or by other means.


## Wine List Parser (Parser)

This component might be one of the most important and also challenging ones. Due to variety and diversity of the wine list formats and presentations, no standard wine naming convention and no one single way how restaurants list their wines, we should use a powerful LLM together with helpful prompt to parse and extract wines from the text file representing restaurant wine list.

Parser should take advantage of the wine list structure to maintain context based on the headers and layouts of wine list. Often such attributes as country, wine type, varietal are maintained via wine list sections and strucutre (layout). 

I also prefer to have a multi-step validation parsing workflow to catch hallucinations and ensure data quality.

Because LLM token consumption will be high I would like to have support for a variety of LLMs from top tier OpenAI, Anthropic, and Gemini to open source, budget providers, and even locally depllyed models.

Examples of wine lists:
- folder 'data/examples' contains pdf files with the wine lists from a few Michelin restaurants
- link to the restaurant Per Se wine list online: http://bw-winelist-website-prod.s3-website-us-west-2.amazonaws.com/f48369c2-1cb6-41e4-86b0-d4dfde4957b9-prod/#/

Keep in mind that some restaurant lists may: 
- include not just wine but other alcoholic beverages and cocktails
- wines by the glass
- include additional information with the wines that is specific to this restaurant only - it will be important to filter this out and not to use it - for examples see the list from Smyth restaurant 'data/examples/smyth.pdf'
- table of content, introductions, and other content complimentary to the wine lists and should not be parsed.

### Wine Ranker (Ranker)

Wine Ranker should run **after** all wines were downloaded and parsed - because its primary goal is to assess a wine's rank in the scope of the as complete and populated wine database as possible.

Wine Ranker algorithm will evolve with time, so that we can always start wine ranker to rank (re-rank) wines based on the latest data and/or the latest algorithm. We can start with a formula that assigns wine rank from 1 to 10 based on the following:
- number of restaurants the wine found in restaurant wine lists
- quality coefficient assigned to restuarant: 3-michelin starred restaurant gets 1.5, 2-michelin starred restaurant gets 1.4, 1-michelin star restuarant 1.3, Michelin Big Gourmand restaurant gets 1.2, Michelin listed restaurant gets 1.1, and regular restaurant gets 1.0 coefficients.
- For example, a wine that is found twice in 3-starred restaurant, 3 times in 1-starred restaurants, and 5 times in Big Gourmand restaurants will get rank = 2 * 1.5 + 3 * 1.3 + 5 * 1.2

Consider other more robust ranking formulas to discuss.

## General Considerations

These remarks may relate to all components.

- Design and implement all business logic and functionality related to restaurant web sites crawling, wine list parsing, ranking, and so on as LangGraph Workflow agents. They don't have to use LLM/AI for their task. Only when necessary enable LLM functionality (as discussed at length above).
- Pick UI framework based on the following considerations: team doesn't have much UI and GUI experience, Python is a language of choice, but we want to have a simple and clear web app so if JavaScript or JS-based approach makes sense use it; ease of deployment and maintining the web app is a priority.
- Consider using CLI to start and control agent lifecycle and application in general. I prefer using package 'typer' for Python CLI. Consider the optimal approach and discuss before making decisions both on how and on implementation package.
- Using LLMs should support plug-and-play for a variety of LLMs. We would like to strike a balance between LLM power and versatility and costs associated with them. Hence, we may use at least the following LLM interchangeably: OpenAI, Anthropic, Azure OpenAI, MiniMax, Qwen, Mistral, and other open source models. Using LangChain addresses this concern but possibly there are even better solutions like using LiteLLM, for example.
- Our priority to have clear, concise, easy to read and bug free implementation, where code is modularized well, have no duplications, functions are not long if possible, complex logic is not hidden but rather self-documenting and follows best practices.

## Challenges

These challenges may relate to all components.

- Wine data schema and standardatization
- Parsing dynamic JavaScript web sites to find wine lists is very impotant as many are not using static html.
- When parsing from the lists and maintaining wines in the database the context that defines some of its properties is very important.
- Optimizing for costs when using LLM providers via caching and smart prompting and workflows is important.
- Wine lists are very diverse and contain some information that is not directly or at all related to the wines.
Ways to classify wines at higher levels - without vintage, without location, and so on.
- Finding the same wines from the winelists is a challenge that maybe addressed by a separate step in parsing or wine ranking components.
- Robust wine ranking based on the frequency appearing in the wine lists, restaurant quality, and the wine list quality.

Backup plan for Crawler (ignore it for now and focus on Michelin website):
Backup plan if Michelin website crawl doesn't work for some reason:
Other alternative (if Michelin website doesn't work for some reason) could be pages in Wikipeida, like ["List of Michelin 3-star restaurants in the United States"](https://en.wikipedia.org/wiki/List_of_Michelin_3-star_restaurants_in_the_United_States), that contain a table "Michelin 3-star restaurants" or similar, which list active and closed restaurants in United States that hold or used to hold 3 Michelin Stars. Using table Crawler navigates to restaurants's wikipedia page, finds its web site from there, then finds a wine list on the restaurant web site. Finally, it downloads and parses a wine list into text retaining its structure (one option to consider).  Other examples of the wikipedia starting page would be (https://en.wikipedia.org/wiki/List_of_Michelin-starred_restaurants_in_Chicago) and [List of Michelin-starred restaurants in New York City](https://en.wikipedia.org/wiki/List_of_Michelin-starred_restaurants_in_New_York_City) and similar. 