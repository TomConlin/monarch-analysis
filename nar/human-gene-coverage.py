import requests
import re

# The purpose of this script to determine what percentage of human protein coding genes
# have associated phenotype data in either humans or in orthologous sequences in other
# species
#
# Some caveats:
# 1. There are a 1 to many mapping between a human gene and its orthologs
# 2. The stats are somewhat misleading in that we are showing coverage for predominately
#    loss of function variants of a gene
# 3. This does not include evidence of functional conservation across species
#
# Where there are cases of many orthologs in a model organism to one human gene, these are
# collapsed into 1 gene in the output count


# Globals and Constants
SCIGRAPH_URL = 'https://scigraph-data.monarchinitiative.org/scigraph'
SOLR_URL = 'https://solr.monarchinitiative.org/solr/golr/select'

# Number of protein coding genes in the human genome
# HGNC (updated 8/8/2016)
# http://www.genenames.org/cgi-bin/statistics
GENE_COUNT = 19008

CURIE_MAP = {
    "http://www.ncbi.nlm.nih.gov/gene/": "NCBIGene",
    "http://purl.obolibrary.org/obo/NCBITaxon_": "NCBITaxon"
}


TAXON_MAP = {
    "Mouse": "http://purl.obolibrary.org/obo/NCBITaxon_10090",
    "ZebraFish": "http://purl.obolibrary.org/obo/NCBITaxon_7955",
    "Worm": "http://purl.obolibrary.org/obo/NCBITaxon_6239",
    "Fly": "http://purl.obolibrary.org/obo/NCBITaxon_7227"
}


def main():

    human_causal = get_causal_gene_phenotype_assocs()
    print("Number of human causual g2p associations: {0}".format(len(human_causal)))

    human_genes = get_human_genes()
    print("Number of human gene cliques: {0}".format(len(human_genes)))
    human_genes_pheno = get_gene_phenotype_list('NCBITaxon:9606')

    for taxon, taxon_iri in TAXON_MAP.items():
        taxon_curie = map_iri_to_curie(taxon_iri)
        gene_list = get_gene_phenotype_list(taxon_curie)
        print("{0}: {1} gene counts".format(taxon, len(gene_list)))

    print("Total human gene-phenotype/disease counts: {0}".format(len(human_genes_pheno)))

    model_only = set()
    all_models = dict()
    model_human_set = set()
    multi_model_set = set()

    for taxon, taxon_iri in TAXON_MAP.items():
        gene_counts = get_orthology_stats(taxon_iri)
        print("Human-{0} orthology count, human: {1}, {2}: {3}".format(
            taxon, gene_counts[0]['human'], taxon, gene_counts[0]['ortholog']))

    for taxon, taxon_iri in TAXON_MAP.items():
        taxon_curie = map_iri_to_curie(taxon_iri)
        results = get_model_gene_stats(taxon_curie, human_genes,
                                       human_genes_pheno,
                                       model_human_set, model_only,
                                       multi_model_set)

        model_only = results['model_only']
        all_models[taxon] = results['model_set']
        model_human_set = results['model_human_set']
        print("{0}: {1} ortholog counts".format(taxon, len(results['model_set'])))
        #print("{0}: {1} unmatched count".format(taxon, len(results['unmatched_set'])))

    print("Models only: {0}".format(len(model_only)))
    print("Models plus human: {0}".format(len(model_human_set)))
    print("Human only: {0}".format(len(human_genes_pheno)-len(model_human_set)))

    print("##########################")

    print("Orthologs with >2 species and no human data: {0}".format(len(multi_model_set)))
    for taxon, taxon_iri in TAXON_MAP.items():
        one_species_count = len(all_models[taxon]) - len(all_models[taxon].intersection(multi_model_set))\
            - len(all_models[taxon].intersection(model_human_set))

        print("{0} only: {1}".format(taxon, one_species_count))


def get_model_gene_stats(taxon_curie, human_genes, human_genes_pheno,
                         model_human_set, model_only, multi_model_set):

    results = {
        'model_set': set(),
        'model_only': model_only,
        'model_human_set': model_human_set,
        'multi_model_set': multi_model_set,
        'unmatched_set': set()
    }

    filters = ['object_closure:"{0}"'.format("UPHENO:0001001"),
               'subject_category:"gene"',
               'subject_taxon: "{0}"'.format(taxon_curie)]
    params = {
        'wt': 'json',
        'rows': 1000,
        'start': 0,
        'q': '*:*',
        'fq': filters,
        'fl': 'subject, subject_ortholog_closure'
    }
    resultCount = params['rows']
    while params['start'] < resultCount:
        solr_request = requests.get(SOLR_URL, params=params)
        response = solr_request.json()
        resultCount = response['response']['numFound']

        for doc in response['response']['docs']:
            foundOrtholog = False
            if 'subject_ortholog_closure' in doc:
                for ortholog in doc['subject_ortholog_closure']:
                    if ortholog in human_genes_pheno:
                        results['model_human_set'].add(ortholog)
                        results['model_set'].add(ortholog)
                        foundOrtholog = True
                    elif ortholog in human_genes:
                        results['model_set'].add(ortholog)
                        if ortholog in results['model_only']:
                            results['multi_model_set'].add(ortholog)
                        else:
                            results['model_only'].add(ortholog)
                        foundOrtholog = True
            if not foundOrtholog:
                results['unmatched_set'].add(doc['subject'])

        params['start'] += params['rows']

    return results


def get_orthology_stats(taxon_iri):

    stats = dict()

    query = "MATCH ({{iri:'http://purl.obolibrary.org/obo/NCBITaxon_9606'}})<-[:RO:0002162]-(gene:gene)" \
            "-[rel:RO:HOM0000017|RO:HOM0000020]-(ortholog:gene)-[:RO:0002162]->" \
            "({{iri:'{0}'}}) " \
            "RETURN COUNT(DISTINCT(ortholog)) as ortholog, COUNT(DISTINCT(gene)) as human".format(taxon_iri)

    scigraph_service = SCIGRAPH_URL + "/cypher/execute.json"
    params = {
        "cypherQuery": query,
        "limit": 10
    }
    request = requests.get(scigraph_service, params=params)
    results = request.json()

    stats['human_gene_count'] = results[0]['human']
    stats['model_gene_count'] = results[0]['ortholog']
    return results


def get_gene_phenotype_list(taxon_curie):
    """
    Get a list of genes with phenotype or disease info indexed in solr
    :param taxon_curie:
    :return:
    """
    filters = ['object_closure:"{0}" OR object_closure:"{1}"'.format("UPHENO:0001001", "DOID:4"),
               'subject_category:"gene"',
               'subject_taxon: "{0}"'.format(taxon_curie)]
    params = {
        'wt': 'json',
        'rows': 0,
        'start': 0,
        'q': '*:*',
        'fq': filters,
        'facet': 'true',
        'facet.mincount': 1,
        'facet.sort': 'count',
        'json.nl': 'arrarr',
        'facet.limit': -1,
        'facet.field': 'subject'
    }
    solr_request = requests.get(SOLR_URL, params=params)
    response = solr_request.json()
    human_genes = {val[0] for val in response['facet_counts']['facet_fields']['subject']
                   if not val[0].startswith("FlyBase")}

    return human_genes


def get_human_genes():

    scigraph_service = SCIGRAPH_URL + "/cypher/execute.json"
    query = "MATCH (gene:gene)-[tax:RO:0002162]->(taxon{iri:'http://purl.obolibrary.org/obo/NCBITaxon_9606'}) " \
            "RETURN DISTINCT gene.iri"
    params = {
        "cypherQuery": query,
        "limit": 100000
    }

    request = requests.get(scigraph_service, params=params)
    results = request.json()

    genes = [key["gene.iri"] for key in results]
    gene_set = {map_iri_to_curie(val) for val in genes if not val.startswith("http://flybase.org")}

    return gene_set


def get_causal_gene_phenotype_assocs():
    print("Fetching causal human gene phenotype and disease associations")
    result_set = set()
    filters = ['object_closure:"{0}" OR object_closure:"{1}"'.format("UPHENO:0001001", "DOID:4"),
               'subject_category:"gene"',
               'subject_taxon: "{0}"'.format('NCBITaxon:9606')]
    params = {
        'wt': 'json',
        'rows': 1000,
        'start': 0,
        'q': '*:*',
        'fq': filters,
        'fl': 'subject, relation, is_defined_by'
    }

    causal_source = ["http://data.monarchinitiative.org/ttl/clinvar.ttl",
                     "http://data.monarchinitiative.org/ttl/omim.ttl",
                     "http://data.monarchinitiative.org/ttl/orphanet.ttl"]
    resultCount = params['rows']
    while params['start'] < resultCount:
        solr_request = requests.get(SOLR_URL, params=params)
        response = solr_request.json()
        resultCount = response['response']['numFound']

        for doc in response['response']['docs']:
            if 'relation' in doc:
                # Filter out likely pathogenic
                if doc['relation'] == 'GENO:0000841':
                    continue

            if 'is_defined_by' in doc\
                    and len([source for source in doc['is_defined_by'] if source in causal_source]) == 0\
                    and doc['is_defined_by'] != ['http://data.monarchinitiative.org/ttl/hpoa.ttl']:
                    continue

            result_set.add(doc['subject'])

        params['start'] += params['rows']

    return result_set


def map_iri_to_curie(iri):
    curie = iri
    for prefix in CURIE_MAP:
        if iri.startswith(prefix):
            curie = re.sub(r"{0}".format(prefix),
                           "{0}:".format(CURIE_MAP[prefix]), iri)
            break
    return curie


if __name__=="__main__":
    main()