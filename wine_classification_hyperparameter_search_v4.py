from functools import partial
from itertools import product
from dataclasses import dataclass

import pandas as pd
import numpy as np
from sklearn.datasets import load_wine
from sklearn.ensemble import RandomForestClassifier 
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, confusion_matrix, classification_report
import plotly.express as px
import plotly
import plotly.figure_factory as ff
from flytekit import task, workflow, ImageSpec, map_task, Deck

sklearn_image_spec = ImageSpec(
    name='wine',
    requirements='requirements_prod.txt',
    registry='us-east4-docker.pkg.dev/union-ai-poc/fbin-union-ai-poc-docker',
    base_image="ghcr.io/flyteorg/flytekit:py3.11-latest"
)

cache_version = "cache-v1"
cache = True

@dataclass
class SearchSpace:
    max_depth: list[int]
    max_features: list[str | None]
    n_estimators: list[int]

@dataclass
class Hyperparameters:
    max_depth: int
    max_features: str | None
    n_estimators: int



@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version)
def get_data() -> pd.DataFrame:
    """
    Read in wine classification data

    Parameters:
        None

    Returns:
        pd.DataFrame: The wine dataset
    """
    # Load Data 
    data = load_wine(as_frame=True).frame

    return data

@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version)
def split_data(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split the data into training and testing sets using stratified sampling
    
    Parameters:
        data (pd.DataFrame): The wine dataset

    Returns:
        Tuple Containing:
            (pd.DataFrame): The training data
            (pd.DataFrame): The testing data
            (pd.DataFrame): The training target
            (pd.DataFrame): The testing target
    """

    # Split Data
    X_data = data.drop(columns = ["target"])
    y_data = data[["target"]]
    X_train, X_test, y_train, y_test = train_test_split(X_data, y_data, test_size=0.25, stratify=y_data, random_state=42)
    X_train, X_val, y_train, y_val = train_test_split(X_train, y_train, test_size=0.25, stratify=y_train, random_state=42)

    return X_train, X_val, X_test, y_train, y_val, y_test
    
@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version)
def train_model(
    X_train: pd.DataFrame,
    y_train: pd.DataFrame,
    hyperparameters: Hyperparameters
) -> RandomForestClassifier:
    """
    Trains a random forest classifier model using the given dataframe and hyperparameters

    Parameters:
        X_train (pd.DataFrame): the training data
        y_train (pd.DataFrame): the training target
        hyperparameters(Hyperparameters): the hyperparameters for the random forest classifier model

    Returns:
        (RandomForestClassifier): the trained random forest classifier model
    """

    model = RandomForestClassifier(**vars(hyperparameters))
    model.fit(X_train, y_train['target'])

    return model

@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version)
def create_search_grid(search_space: SearchSpace) -> list[Hyperparameters]:
    """
    Generate a search grid based on the given dictionary of lists.

    Parameters:
        grid (SearchSpace): A dictionary where the keys represent the parameter names and the values are lists of possible values for each parameter

    Returns:
        list[Hyperparameters]: Each possible permutation of the hyperparameter choices.
    """
    
    keys = search_space.__annotations__.keys()
    values = [getattr(search_space, key) for key in keys]
    
    grid = [Hyperparameters(**dict(zip(keys, combination))) for combination in product(*values)]
    
    return grid

@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version, enable_deck=True)
def compare_model_results(
    X_val: pd.DataFrame,
    y_val: pd.DataFrame,
    models: list[RandomForestClassifier],
    force_plot: bool = False
) -> RandomForestClassifier:
    """
    Compares the results of different models on a given dataframe using specified hyperparameters

    Parameters:
        X_val (pd.DataFrame): the validation data
        y_val (pd.DatFrame): the validation target
        models (List[RandomForestClassifier]): list of models to compare
        force_plot (bool): force plotly to plot (for example for notebook)

    Returns:
        RandomForestClassifier: The best performing model based on F1 score
    """
    
    param_names = list(Hyperparameters.__annotations__.keys())

    # Collect all the scores and hyperparameters
    search_parameters_dict = {}
    search_parameters_dict['scores'] = []
    for name in param_names:
        search_parameters_dict[name] = []
    for model in models:
        yhat = model.predict(X_val)
        score = f1_score(y_pred=yhat, y_true=y_val, average='macro')
        search_parameters_dict['scores'].append(score)
        for name in param_names:
            search_parameters_dict[name].append(getattr(model, name))

    # Select the best model
    best_index = np.array(search_parameters_dict['scores']).argmax()
    best_model = models[best_index]

    # Create dataframe of hyperparameters and scores
    search_parameters = pd.DataFrame(search_parameters_dict)

    # Create figure for parameters explored
    fig = px.parallel_coordinates(
        search_parameters, color="scores",
        dimensions=param_names,
        color_continuous_scale=px.colors.diverging.Tealrose,
        color_continuous_midpoint=2
    )
    fig.update_layout(
        title_text='Parellel Coordinates',
        xaxis = dict(title='Hyperparameter Names'),
        yaxis = dict(title='Hyperparameter Value')
    )
    deck_obj = Deck("Parallel Coordinates")
    deck_obj.append(plotly.io.to_html(fig))
    deck_obj.append(search_parameters.to_html())

    if force_plot:
        fig.show()

    return best_model

def plot_confusion_matrix(y_true: pd.DataFrame, y_pred: pd.DataFrame, title: str):
    """
    Plots a confusion matrix based on the true labels and predicted labels.

    Parameters:
        y_true (pd.DataFrame): The true labels.
        y_pred (pd.DataFrame): The predicted labels.
        title (str): The title of the plot.

    Returns:
        (plotly.graph_objects.Figure): The confusion matrix plot.
    """
    
    # Create confusion matrix
    array = confusion_matrix(y_true, y_pred)
    labels = sorted(y_true.target.unique().tolist())

    # change each element of z to type string for annotations
    z_text = [[str(y) for y in x] for x in array.tolist()]

    # set up figure 
    fig = ff.create_annotated_heatmap(array, x=labels, y=labels, annotation_text=z_text, colorscale='Viridis')

    # add title
    fig.update_layout(
        title_text=title,
        xaxis = dict(title='Predicted Label'),
        yaxis = dict(title='Actual Label')
    )
    
    return fig

@task(container_image=sklearn_image_spec, cache=cache, cache_version=cache_version, enable_deck=True)
def analyze_model(
    X_train: pd.DataFrame,
    y_train: pd.DataFrame,
    X_val: pd.DataFrame,
    y_val: pd.DataFrame,
    X_test: pd.DataFrame,
    y_test: pd.DataFrame,
    model: RandomForestClassifier,
    force_plot: bool = False
) -> None:
    """
    Analyzes the performance of a RandomForestClassifier model on a given dataframe.
    Parameters:
        X_train (pd.DataFrame): The training data
        y_train (pd.DataFrame): The training target
        X_val (pd.DataFrame): The validation data
        y_val (pd.DataFrame): The validation target
        X_test (pd.DataFrame): The testing data
        y_test (pd.DataFrame): The testing target
        model (RandomForestClassifier): The trained RandomForestClassifier model.
        dataframe (pd.DataFrame): The dataframe containing the data for analysis.
        force_plot (bool, optional): Whether to force plotly to plot (for example for notebook)
    Returns:
        None
    """
    # Create predicted labels
    yhat_train = model.predict(X_train)
    yhat_val = model.predict(X_val)
    yhat_test = model.predict(X_test)
    
    # Create confusion matrix plots
    confusion_matrix_plot_train = plot_confusion_matrix(y_true=y_train, y_pred=yhat_train, title="Training Set")
    confusion_matrix_plot_val = plot_confusion_matrix(y_true=y_val, y_pred=yhat_val, title="Validation Set")
    confusion_matrix_plot_test = plot_confusion_matrix(y_true=y_test, y_pred=yhat_test, title="Test Set")

    # Create classification reports
    class_report_train = pd.DataFrame(classification_report(y_train, yhat_train, output_dict=True))
    class_report_val = pd.DataFrame(classification_report(y_val, yhat_val, output_dict=True))
    class_report_test = pd.DataFrame(classification_report(y_test, yhat_test, output_dict=True))

    # Add to the flyte deck
    deck_obj = Deck("Confusion Matrix")
    deck_obj.append(confusion_matrix_plot_train.to_html())
    deck_obj.append(class_report_train.to_html())
    deck_obj.append(confusion_matrix_plot_val.to_html())
    deck_obj.append(class_report_val.to_html())
    deck_obj.append(confusion_matrix_plot_test.to_html())
    deck_obj.append(class_report_test.to_html())

    # Display charts and data if displaying in notebook
    if force_plot:
        confusion_matrix_plot_train.show()
        print(class_report_train)
        confusion_matrix_plot_val.show()
        print(class_report_val)
        confusion_matrix_plot_test.show()
        print(class_report_test)

@workflow
def training_workflow(
    search_space: SearchSpace = SearchSpace(
        max_depth=[50, 100], 
        max_features=[None, 'sqrt'], 
        n_estimators=[100, 2000])
    ) -> RandomForestClassifier:
    """
    Create workflow DAG (composed of tasks) to train a RandomForestClassifier on the wine dataset

    Parameters:
        None

    Returns:
        (RandomForestClassifier): The best model
    """
    # Load wine data
    data = get_data()

    # Split data
    X_train, X_val, X_test, y_train, y_val, y_test = split_data(data=data)

    # Create search grid
    hyperparameters = create_search_grid(search_space=search_space)

    # Train models in parallel
    partial_function = partial(train_model, X_train=X_train, y_train=y_train)
    map_task_obj = map_task(partial_function)
    models = map_task_obj(hyperparameters=hyperparameters)

    # Return the best model 
    best_model = compare_model_results(X_val, y_val, models)

    # Analyze the best model
    analyze_model(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        X_test=X_test,
        y_test=y_test,
        model=best_model
    )

    return best_model

if __name__ == "__main__":
    training_workflow()